"""
Download dos ZIPs de CNPJ via WebDAV da Receita Federal.

Inspirado em https://github.com/rictom/cnpj-sqlite (dados_cnpj_baixa.py)
e https://github.com/caiopizzol/cnpj-data-pipeline.

Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import requests

from dockdb_cnpj.config import LAST_SYNC_PATH, SHARE_TOKEN, WEBDAV_BASE, ZIP_DIR, ensure_dirs

__author__ = "Matheus Cavalcanti Pestana"
__email__ = "matheus.pestana@fgv.br"

DAV_NS = {"d": "DAV:"}
USER_AGENT = (
    "Mozilla/5.0 (compatible; DockDB-CNPJ/0.1; +https://github.com/; "
    "Matheus Cavalcanti Pestana)"
)


@dataclass
class RemoteListing:
    ano_mes: str
    url_base: str
    arquivos: list[str]
    url_pagina: str


def consulta_base_webdap(
    share_token: str = SHARE_TOKEN,
    base_url: str = WEBDAV_BASE,
) -> RemoteListing:
    """Lista o mês mais recente e os .zip disponíveis."""
    url = base_url.rstrip("/") + "/"
    response = requests.request(
        "PROPFIND",
        url,
        auth=(share_token, ""),
        headers={"Depth": "1", "User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)

    directories: list[str] = []
    for resp in root.findall("d:response", DAV_NS):
        href_el = resp.find("d:href", DAV_NS)
        if href_el is None or not href_el.text:
            continue
        match = re.search(r"(\d{4}-\d{2})/?$", href_el.text)
        if match:
            directories.append(match.group(1))

    if not directories:
        raise RuntimeError(
            "Nenhuma pasta YYYY-MM encontrada no WebDAV. "
            "Atualize CNPJ_SHARE_TOKEN (veja README)."
        )

    directories.sort()
    ultimo = directories[-1]

    response = requests.request(
        "PROPFIND",
        f"{url}{ultimo}/",
        auth=(share_token, ""),
        headers={"Depth": "1", "User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)

    files: list[str] = []
    for resp in root.findall("d:response", DAV_NS):
        href_el = resp.find("d:href", DAV_NS)
        if href_el is None or not href_el.text:
            continue
        match = re.search(r"/([^/]+\.zip)$", href_el.text, re.IGNORECASE)
        if match:
            files.append(match.group(1))

    files = sorted(set(files))
    url_base = (
        f"https://arquivos.receitafederal.gov.br/public.php/dav/files/"
        f"{share_token}/{ultimo}/"
    )
    url_pagina = f"https://arquivos.receitafederal.gov.br/index.php/s/{share_token}"
    return RemoteListing(
        ano_mes=ultimo,
        url_base=url_base,
        arquivos=files,
        url_pagina=url_pagina,
    )


def _remote_size(url: str) -> int | None:
    try:
        r = requests.head(url, headers={"User-Agent": USER_AGENT}, timeout=30, allow_redirects=True)
        if r.status_code >= 400:
            return None
        cl = r.headers.get("Content-Length")
        return int(cl) if cl else None
    except Exception:
        return None


def needs_download(dest: Path, url: str) -> bool:
    if not dest.exists() or dest.stat().st_size == 0:
        return True
    remote = _remote_size(url)
    if remote is None:
        return False  # já existe; sem HEAD confiável, não rebaixa
    return dest.stat().st_size != remote


def download_file(url: str, dest: Path, *, force: bool = False) -> bool:
    """Baixa um arquivo. Retorna True se baixou, False se pulou."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not force and not needs_download(dest, url):
        print(f"  [skip] {dest.name}")
        return False

    print(f"  [get]  {dest.name}")
    with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=600) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(dest)
    return True


def download_all(
    listing: RemoteListing | None = None,
    *,
    zip_dir: Path = ZIP_DIR,
    only_missing: bool = False,
    force: bool = False,
) -> RemoteListing:
    """Baixa todos os ZIPs do mês mais recente (ou só os faltantes)."""
    ensure_dirs()
    listing = listing or consulta_base_webdap()
    print(f"Competência remota: {listing.ano_mes}")
    print(f"Arquivos: {len(listing.arquivos)}")
    print(f"Destino: {zip_dir}")

    baixados = 0
    for name in listing.arquivos:
        url = listing.url_base + name
        dest = zip_dir / name
        if only_missing and dest.exists() and dest.stat().st_size > 0 and not force:
            if not needs_download(dest, url):
                print(f"  [skip] {name}")
                continue
        if download_file(url, dest, force=force):
            baixados += 1
            time.sleep(0.2)

    print(f"Download concluído. Novos/atualizados: {baixados}/{len(listing.arquivos)}")
    return listing


def save_sync_meta(listing: RemoteListing, extra: dict | None = None) -> None:
    ensure_dirs()
    payload = {
        "ano_mes": listing.ano_mes,
        "arquivos": listing.arquivos,
        "url_pagina": listing.url_pagina,
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "author": "Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>",
    }
    if extra:
        payload.update(extra)
    LAST_SYNC_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_sync_meta() -> dict | None:
    if not LAST_SYNC_PATH.exists():
        return None
    return json.loads(LAST_SYNC_PATH.read_text(encoding="utf-8"))
