# Open Instagram API

A self-hosted HTTP API for Instagram, reverse-engineered from the Instagram website.

> Unofficial and not affiliated with Instagram or Meta. Automating an account can get it restricted, so try it on a test account first.

## Setup

1. Export your instagram.com cookies to `cookies.json` (export while logged in; keep that browser logged in).
   Check the file with `python3 check_cookies.py cookies.json`.
2. Install and run:

```bash
pip install -r requirements.txt
python3 server.py
```

The API runs at `http://127.0.0.1:8765`. Send the token from `api_token` as `Authorization: Bearer <token>`.

## Endpoints

```
Messages
GET    /threads                              list chats (?folder=requests for message requests)
GET    /threads/{id}/messages                read messages (?cursor= for older ones)
POST   /threads/{id}/messages                send {"text": "hi"}
POST   /threads/{id}/photos                  send a photo (multipart: file)
DELETE /threads/{id}/messages/{mid}          unsend
POST   /threads/{id}/messages/{mid}/reactions   react {"emoji": "❤"}   (DELETE to remove)
POST   /threads/{id}/seen                    mark as seen
POST   /threads/{id}/accept                  accept a message request
GET    /updates?since_ms=0                   new incoming messages

Browsing
GET    /search?q=nasa                        users, hashtags, places
GET    /users/{username}                     profile
GET    /users/{username}/posts               posts (?cursor= for the next page)
GET    /users/{username}/reels               reels
GET    /users/{username}/tagged              tagged posts
GET    /users/{username}/stories             live stories
GET    /users/{username}/highlights          highlights   ->  GET /highlights/{id}
GET    /users/{username}/followers           followers (also /following)
GET    /users/{username}/friendship          follow status
GET    /media/{shortcode}                    post or reel
GET    /media/{shortcode}/comments           comments     ->  GET /comments/{pk}/replies
GET    /media/{shortcode}/likers             likers
GET    /feed/timeline                        home feed (also /feed/reels, /feed/explore)
GET    /stories/tray                         stories from people you follow
GET    /tags/{tag}                           hashtag posts
GET    /locations/{id}                       location posts
GET    /notifications                        activity
GET    /saved                                saved collections

Actions
POST   /media/{shortcode}/like               like (DELETE to unlike)
POST   /media/{shortcode}/save               save (DELETE to unsave)
POST   /users/{username}/follow              follow (DELETE to unfollow)
POST   /media/{shortcode}/comments           comment {"text": "nice"}
DELETE /media/{shortcode}/comments/{pk}      delete a comment
POST   /media/{shortcode}/share              send a post/reel to a chat {"thread_id": "..."} or {"users": ["name"]}

Publishing and account
POST   /media                                post 1 image, or 2-10 as a carousel (multipart: files, caption)
PATCH  /media/{shortcode}                    edit caption {"caption": "..."}
GET    /account                              your profile settings
PATCH  /account                              edit {"biography", "first_name", "username"}
PUT    /account/privacy                      {"private": true}
```

Add `?raw=1` to read endpoints to get Instagram's response untouched.

## Realtime

```
GET    /events                               live DM events (Server-Sent Events), new messages in ~0.5 s
GET    /events/status                        connected / disconnected
```

```bash
curl -N -H "Authorization: Bearer $TOKEN" localhost:8765/events
data: {"type": "message", "message": {"id": "...", "kind": "reel", "text": null, "thread_fbid": "...", ...}}
```

The server holds one connection to Instagram's own realtime gateway (the WebSocket instagram.com listens on)
and reconnects by itself.

**Not supported:** blocking/restricting, deleting posts, publishing reels, stories and highlights, editing or muting
messages. Instagram only accepts these from its own website code or app, not from a script. See
[docs/PROTOCOL.md](docs/PROTOCOL.md).

## Example

`examples/reel_autoreply.py` auto-replies to reels while you're busy, about a second after they arrive.

## License

MIT
