# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "google-api-python-client>=2.100",
#     "google-auth-oauthlib>=1.2",
# ]
# ///
"""Envoi de videos sur YouTube via l'API Data v3.

Usage :
    uv run tools/video/youtube_upload.py auth
    uv run tools/video/youtube_upload.py upload VIDEO --title "..." [options]   (simulation)
    uv run tools/video/youtube_upload.py upload VIDEO --title "..." --yes       (envoi reel)

Secrets (hors du depot) : %USERPROFILE%\\.gobelins_youtube\\
    client_secret.json  <- identifiant OAuth "Application de bureau" telecharge depuis Google Cloud
    token.json          <- cree automatiquement au premier `auth`

Rappel : tant que le projet Google Cloud n'a pas passe l'audit, YouTube force
les videos envoyees par l'API en PRIVE, quel que soit --privacy.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
SECRETS_DIR = Path.home() / ".gobelins_youtube"
CLIENT_SECRET = SECRETS_DIR / "client_secret.json"
TOKEN = SECRETS_DIR / "token.json"
CATEGORY_GAMING = "20"


def get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:  # token revoque / expire (7 j en mode "Test")
            print(f"Rafraichissement impossible ({e}), nouvelle autorisation.")
            creds = None
    if not creds or not creds.valid:
        if not CLIENT_SECRET.exists():
            sys.exit(f"client_secret.json introuvable : {CLIENT_SECRET}")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def cmd_auth(_args):
    get_credentials()
    print(f"OK, token enregistre : {TOKEN}")


def read_text_arg(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def cmd_upload(args):
    video = Path(args.video)
    if not video.is_file():
        sys.exit(f"Video introuvable : {video}")
    description = read_text_arg(args.description)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    body = {
        "snippet": {
            "title": args.title,
            "description": description,
            "tags": tags,
            "categoryId": args.category,
            "defaultLanguage": args.lang,
            "defaultAudioLanguage": args.lang,
        },
        "status": {
            "privacyStatus": args.privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    if args.publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = args.publish_at

    size_mb = video.stat().st_size / 1_048_576
    print("=== Envoi YouTube ===")
    print(f"Fichier     : {video} ({size_mb:.1f} Mo)")
    print(f"Titre       : {args.title}")
    print(f"Tags        : {', '.join(tags) or '-'}")
    print(f"Visibilite  : {body['status']['privacyStatus']}"
          + (f" (publication {args.publish_at})" if args.publish_at else ""))
    print(f"Langue      : {args.lang} | categorie {args.category}")
    print(f"Miniature   : {args.thumbnail or '-'}")
    print("Description :")
    print(description or "-")
    print("=====================")

    if len(args.title) > 100:
        sys.exit("Titre > 100 caracteres, refuse par YouTube.")
    if not args.yes:
        print("Simulation : rien envoye. Ajoute --yes pour envoyer.")
        return

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=get_credentials())
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  {int(status.progress() * 100)} %")
    vid = response["id"]
    print(f"Envoye : https://youtu.be/{vid}")
    print(f"Statut renvoye : {response.get('status', {}).get('privacyStatus')}")

    if args.thumbnail:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(args.thumbnail)).execute()
            print("Miniature appliquee.")
        except Exception as e:
            print(f"Miniature refusee ({e}). Chaine verifiee par telephone requise.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth", help="autorisation OAuth (une fois)").set_defaults(func=cmd_auth)

    u = sub.add_parser("upload", help="envoyer une video")
    u.add_argument("video")
    u.add_argument("--title", required=True)
    u.add_argument("--description", help="texte, ou @fichier.txt")
    u.add_argument("--tags", help="separes par des virgules")
    u.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    u.add_argument("--publish-at", help="ISO 8601 UTC, ex 2026-11-25T17:00:00Z (force private jusque-la)")
    u.add_argument("--lang", default="fr")
    u.add_argument("--category", default=CATEGORY_GAMING)
    u.add_argument("--thumbnail", help="image jpg/png < 2 Mo")
    u.add_argument("--yes", action="store_true", help="envoyer pour de vrai")
    u.set_defaults(func=cmd_upload)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
