# Open Instagram API

A self-hosted HTTP API for Instagram. Messaging only, for now.

> Unofficial and not affiliated with Instagram or Meta. Automating an account can get it restricted, so try it on a test account first.

## Setup

1. Export your instagram.com cookies to `cookies.json`.
2. Install and run:

```bash
pip install -r requirements.txt
python3 server.py
```

The API runs at `http://127.0.0.1:8765`. Send the token from `api_token` as `Authorization: Bearer <token>`.

## Endpoints

```
GET  /threads                     list chats (?folder=requests for message requests)
GET  /threads/{id}/messages       read messages
POST /threads/{id}/messages       send {"text": "hi"}
POST /threads/{id}/seen           mark as seen
POST /threads/{id}/accept         accept a message request
GET  /updates?since_ms=0          new incoming messages
```

## Example

`examples/reel_autoreply.py` auto-replies to reels while you're busy.

## How it works

See [docs/PROTOCOL.md](docs/PROTOCOL.md).

## License

MIT
