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
    expected = "38e7171e9e8c4a871ff84765848f0290ca34a44e"
    url = "https://api.github.com/repos/Re-UE4SS/UEPseudo/git/commits/" + expected
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nola-sdk-access-check",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        print("SDK_ACCESS_HTTP=" + str(error.code))
        print("::error::The build credential cannot read the required UEPseudo commit. Check its repository read permission and the account's Epic Games access.")
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
