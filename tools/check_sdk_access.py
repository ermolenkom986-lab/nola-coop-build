"""Check the build credential without logging it or downloading private source."""
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    token = os.environ.get("UE4SS_READ_TOKEN", "")
    if not token:
        print("SDK_SECRET_CONFIGURED=false")
        print("::error::Repository Actions secret UE4SS_READ_TOKEN is missing. Account linking alone does not grant the build runner access to UEPseudo.")
        return 1
    print("SDK_SECRET_CONFIGURED=true")
    def fetch(path):
        request = urllib.request.Request("https://api.github.com/" + path, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nola-sdk-access-check",
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.load(response), response.headers
        except urllib.error.HTTPError as error:
            return error.code, {}, error.headers

    expected = "38e7171e9e8c4a871ff84765848f0290ca34a44e"
    try:
        status, identity, headers = fetch("user")
        print("SDK_TOKEN_IDENTITY_HTTP=" + str(status))
        if status != 200:
            print("::error::The stored build token is not accepted by GitHub. Replace it with a valid unexpired token.")
            return 1
        print("SDK_TOKEN_ACCOUNT=" + identity["login"])
        scopes = headers.get("X-OAuth-Scopes")
        if scopes is not None:
            has_repo = "repo" in {s.strip() for s in scopes.split(",")}
            print("SDK_CLASSIC_REPO_SCOPE=" + str(has_repo).lower())
        else:
            print("SDK_CLASSIC_REPO_SCOPE=not_reported")
        engine_status, _, _ = fetch("repos/EpicGames/UnrealEngine")
        print("SDK_UNREAL_ENGINE_HTTP=" + str(engine_status))
        repo_status, _, repo_headers = fetch("repos/Re-UE4SS/UEPseudo")
        print("SDK_UEPSEUDO_REPOSITORY_HTTP=" + str(repo_status))
        if "required" in repo_headers.get("X-GitHub-SSO", ""):
            print("SDK_SSO_AUTHORIZATION=required")
        if repo_status != 200:
            print("::error::The token is valid but cannot read Re-UE4SS/UEPseudo. Epic account linking, invitation acceptance or access to this private fork is still missing for this credential.")
            return 1
        status, data, _ = fetch("repos/Re-UE4SS/UEPseudo/git/commits/" + expected)
        print("SDK_ACCESS_HTTP=" + str(status))
        if status != 200:
            print("::error::UEPseudo is accessible but the pinned dependency revision is not. Check the revision before building.")
            return 1
    except (urllib.error.URLError, TimeoutError):
        print("::error::The SDK access check could not reach GitHub; retry the check.")
        return 1
    if data.get("sha") != expected:
        print("::error::GitHub returned an unexpected dependency revision.")
        return 1
    print("SDK_ACCESS=ready")
    print("SDK_COMMIT=" + expected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
