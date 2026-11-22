"""Package a verified custom DLL with the unchanged official NOLA 1.4.2 payload.

Requires pefile. Does not download files, run the game or modify an installation.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

import pefile


BASE_SHA256 = "2085bd7c14ea9c902f3c4fb70668405f019a54a56abcc991f160bff71df6bab2"
BASE_ROOT = "NOLA-Auto/"
DLL_REL = "game/Stalker2/Binaries/Win64/ue4ss/Mods/NolaNative/dlls/main.dll"
UE4SS_REL = "game/Stalker2/Binaries/Win64/ue4ss/UE4SS.dll"
VERSION = "1.4.2-sxfix-preview1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def exports(pe):
    return {entry.name for entry in pe.DIRECTORY_ENTRY_EXPORT.symbols if entry.name}


def check_binary(dll, stock_dll, ue4ss):
    require(dll != stock_dll, "The supplied DLL is the unmodified official DLL, not the fix")
    with pefile.PE(data=dll) as pe, pefile.PE(data=stock_dll) as old, pefile.PE(data=ue4ss) as sdk:
        require(pe.FILE_HEADER.Machine == 0x8664, "The custom DLL must be Windows x64")
        require(pe.FILE_HEADER.Characteristics & 0x2000, "The artifact is not a DLL")
        require({b"start_mod", b"uninstall_mod"} <= exports(pe), "Missing UE4SS mod entry points")
        imports = getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
        sdk_imports = [e for e in imports if e.dll.lower() == b"ue4ss.dll"]
        require(len(sdk_imports) == 1, "Expected an import table for UE4SS.dll")
        sdk_names = exports(sdk)
        sdk_ordinals = {e.ordinal for e in sdk.DIRECTORY_ENTRY_EXPORT.symbols}
        missing = []
        for entry in sdk_imports[0].imports:
            if (entry.name and entry.name not in sdk_names) or (not entry.name and entry.ordinal not in sdk_ordinals):
                missing.append(entry.name.decode("ascii") if entry.name else "ordinal " + str(entry.ordinal))
        require(not missing, "The shipped UE4SS DLL lacks required exports: " + ", ".join(missing))
        old_dlls = {e.dll.lower() for e in old.DIRECTORY_ENTRY_IMPORT}
        extra = [e.dll.decode("ascii") for e in imports
                 if e.dll.lower() not in old_dlls and not e.dll.lower().startswith((b"api-ms-win-", b"ext-ms-"))]
        require(not extra, "Additional runtime dependencies need review: " + ", ".join(extra))
        return {"machine": "AMD64", "ue4ss_imports_checked": len(sdk_imports[0].imports),
                "imported_dlls": sorted(e.dll.decode("ascii") for e in imports)}


def read_base(path):
    require(sha256(path.read_bytes()) == BASE_SHA256, "Official NOLA-Auto.zip SHA256 does not match v1.4.2")
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, "The base archive is corrupt")
        files = {}
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            require(entry.filename.startswith(BASE_ROOT), "Unexpected archive root")
            rel = entry.filename[len(BASE_ROOT):]
            require(not PurePosixPath(rel).is_absolute() and ".." not in PurePosixPath(rel).parts,
                    "Unsafe archive member")
            require(rel not in files, "Duplicate archive member")
            files[rel] = archive.read(entry)
    for line in files["files/CHECKSUMS.txt"].decode("ascii").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        require(hashlib.md5(files["files/" + rel]).hexdigest() == digest, "Base payload checksum mismatch: " + rel)
    return files


def instructions(info):
    return f"""# NOLA {VERSION}: тестовый комплект

Это неофициальная сборка на основе NOLA 1.4.2 с исправлением передачи сохранений.
DLL собрана на Windows и прошла проверки кода и встроенных таблиц. Проверки
в самой игре ещё не проводились; устранение вашего 15-минутного вылета не доказано.

## Если NOLA 1.4.2 уже установлена и соединение через Radmin работает

1. На обоих ПК закройте игру и сохраните резервную копию своих сохранений.
2. В папке игры откройте
   `Stalker2\\Binaries\\Win64\\ue4ss\\Mods\\NolaNative\\dlls`.
3. Скопируйте старый `main.dll` в отдельную папку для отката.
4. Замените его файлом
   `files\\game\\Stalker2\\Binaries\\Win64\\ue4ss\\Mods\\NolaNative\\dlls\\main.dll`
   из этого архива. Сделайте это на обоих ПК. Настройки Radmin менять не нужно.
5. Запустите игру. Хост выбирает Host co-op, друг — Join co-op.

Этот способ рассчитан на установленный официальный комплект 1.4.2. При другой
версии мода сначала установите полный комплект, описанный ниже.

Для отката закройте игру и верните сохранённую копию `main.dll` на обоих ПК.

## Полная установка

1. Полностью распакуйте архив и закройте игру.
2. Запустите `install.bat`. Если игра не найдена, укажите её папку вручную.
3. Для Radmin выберите режим IP/LAN/VPN. Укажите адрес другого игрока из Radmin,
   как при уже работавшем подключении.
4. Установите одинаковый комплект на оба компьютера.

Используется установщик исходного проекта. Он делает резервные копии заменяемых
файлов; `uninstall.bat` выполняет удаление по его журналу. При повторной полной
установке он сначала отменяет прошлую установку NOLA, поэтому удаление полного
комплекта не следует считать возвратом к предыдущей версии мода. Для возврата
к обычной NOLA 1.4.2 установите её официальный комплект заново.

## Проверка и отчёт о сбое

После установки проверьте подключение и загрузку сохранения, затем поиграйте
вдвоём 30–40 минут, включая переход между локациями и повторное подключение.
Это поможет проверить сценарий, в котором раньше вылетал клиент; один успешный
сеанс ещё не доказывает отсутствие всех вылетов.

- DLL SHA256: `{info['dll_sha256']}`.
- Исходный коммит этой сборки: `{info['source_commit']}`.
- Запуск сборки: {info['run_url']}.
- `build-info.json`, `binary-check.json` и `validation/` содержат сведения о проверках.
- `source/` содержит соответствующие исходники NOLA, `LICENSE-NOLA.txt` — лицензию.
- Если игра вылетит, сохраните `UE4SS.log` именно с ПК, где произошёл вылет,
  до следующего запуска. Он находится в `Stalker2\\Binaries\\Win64\\ue4ss`.
- Если появилась новая папка в `%LOCALAPPDATA%\\Stalker2\\Saved\\Crashes`,
  сохраните из неё `CrashContext.runtime-xml` с временем этого вылета.

Исходная NOLA 1.4.2 рассчитана на Steam build 25382007 с DLC Cost of Hope,
согласно INSTALL.md. Совместимость с другими сборками игры этим исправлением
не добавлялась; ваша локальная версия игры пока не проверена.
Оригинальные инструкции находятся в README.md и INSTALL.md.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--base-zip", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Output already exists; choose a new filename")
    info = json.loads((args.artifact_dir / "build-info.json").read_text(encoding="utf-8-sig"))
    dll = (args.artifact_dir / "main.dll").read_bytes()
    require(sha256(dll) == info["dll_sha256"], "Custom DLL does not match the build manifest")
    require(info.get("upstream_commit") == "be9cc362e00753e1676205a47a6af50f6f057fda", "Wrong upstream revision")
    require(info.get("ue4ss_commit") == "5e627997bf265ae6fc89d23357543d8c8ac05a6f", "Wrong UE4SS revision")
    revision = info["source_commit"]
    require(len(revision) == 40 and all(c in "0123456789abcdef" for c in revision), "Invalid source revision")
    files = read_base(args.base_zip)
    binary_check = check_binary(dll, files["files/" + DLL_REL], files["files/" + UE4SS_REL])
    tests = {}
    for name in ("sxrecv.log", "sxreq.log", "release-tables.log"):
        tests[name] = (args.artifact_dir / name).read_bytes()
        require(b"FAIL" not in tests[name] and b"SKIP" not in tests[name], "Failed or skipped check in " + name)
    require(b"ALL PASS (0 failed, 16 cases)" in tests["sxrecv.log"], "Receiver tests were not verified")
    require(b"ALL PASS (0 failed)" in tests["sxreq.log"], "Request tests were not verified")
    require(b"class a tables embedded byte-identical" in tests["release-tables.log"], "Embedded data was not verified")
    files["files/" + DLL_REL] = dll
    sums = []
    for line in files["files/CHECKSUMS.txt"].decode("ascii").splitlines():
        if line.strip():
            _, rel = line.split("  ", 1)
            sums.append(hashlib.md5(files["files/" + rel]).hexdigest() + "  " + rel)
    files["files/CHECKSUMS.txt"] = ("\n".join(sums) + "\n").encode("ascii")
    marker = b"$NolaVersion = '1.4.2'"
    require(files["nola_install.ps1"].count(marker) == 1, "Unexpected installer version marker")
    files["nola_install.ps1"] = files["nola_install.ps1"].replace(marker, ("$NolaVersion = '" + VERSION + "'").encode("ascii"))
    files["README_FIRST_RU.md"] = instructions(info).encode("utf-8")
    files["build-info.json"] = (json.dumps(info, indent=2) + "\n").encode("utf-8")
    files["binary-check.json"] = (json.dumps(binary_check, indent=2) + "\n").encode("utf-8")
    for name, contents in tests.items():
        files["validation/" + name] = contents
    files["LICENSE-NOLA.txt"] = subprocess.check_output(["git", "show", revision + ":LICENSE"], cwd=args.repo)
    files["source/nola-source-" + revision[:12] + ".zip"] = subprocess.check_output(
        ["git", "archive", "--format=zip", revision], cwd=args.repo)
    files["SHA256SUMS.txt"] = ("\n".join(sha256(data) + "  " + name for name, data in sorted(files.items())) + "\n").encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            archive.writestr("NOLA-SXFIX-Preview/" + name, data)
    with zipfile.ZipFile(args.output) as archive:
        require(archive.testzip() is None, "The generated archive is corrupt")
    print("Package:", args.output)
    print("SHA256:", sha256(args.output.read_bytes()))


if __name__ == "__main__":
    main()
