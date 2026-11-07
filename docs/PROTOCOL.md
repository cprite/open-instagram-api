# Instagram web client: protocol notes

These are observations from the Instagram web client (`www.instagram.com`, web build `1053591692`, November 2026),
captured over the Chrome DevTools Protocol and analysed with [REA](https://github.com/morluto/rea). IDs below are
placeholders.

## 1. The legacy REST API is gone (on web)

| Request | Result with a valid session |
|---|---|
| `GET www.instagram.com/api/v1/direct_v2/inbox/` | `404` HTML page, rendered as logged-out |
| `GET www.instagram.com/api/v1/direct_v2/get_badge_count/` | `404` |
| `GET i.instagram.com/api/v1/direct_v2/inbox/` | `400 {"status":"Prompt has contribution","error_code":4415001}` (mobile clients only) |
| `GET www.instagram.com/api/v1/accounts/edit/web_form_data/` | `200`, so the session itself is fine |

## 2. GraphQL "Slide" messaging

`POST https://www.instagram.com/api/graphql`, `application/x-www-form-urlencoded`. The operations are persisted
queries, selected by `doc_id`.

### Form fields

```
av=<actor id>  __d=www  __user=0  __a=1  __req=<hex counter>  __hs=<haste_session>  dpr=1  __ccg=EXCELLENT
__rev=<server_revision>  __hsi=<hsi>  __comet_req=7  fb_dtsg=<DTSGInitialData token>  jazoest=2<sum of fb_dtsg char codes>
lsd=<LSD token>  __spin_r=<rev>  __spin_b=trunk  __spin_t=<spin_t>  fb_api_caller_class=RelayModern
fb_api_req_friendly_name=<Operation>  server_timestamps=true  variables=<json>  doc_id=<id>
```

All page-scoped values are in the HTML of `/direct/inbox/`:
`"DTSGInitialData",[],{"token":…}`, `"LSD",[],{"token":…}`, `"actorID"`, `"server_revision"`, `"haste_session"`,
`"hsi"` and `"__spin_t"`. Without `__hs`, `__hsi`, `__rev` and `__spin_*`, the server answers
`for (;;);{"error":1357054,…}`.

### Headers

`X-FB-Friendly-Name: <Operation>`, `X-FB-LSD`, `X-CSRFToken: <csrftoken cookie>`, `X-IG-App-ID: 936619743392459`,
`X-ASBD-ID: 359341`, `Origin`/`Referer: https://www.instagram.com/...`, and `Sec-Fetch-*: same-origin/cors/empty`.

### Discovering doc_ids

Each operation ships as a tiny module in the JS bundles referenced by the inbox HTML:

```js
__d("IGDirectTextSendMutation_instagramRelayOperation",[],(function(a,b,c,d,e,f){e.exports="<doc_id>"}),null);
```

One inbox page references around 456 scripts that define around 334 operations.

### Operations

| Operation | Variables (observed) | Result path |
|---|---|---|
| `PolarisDirectInboxQuery` | `device_id_for_iris_subscription` (web device UUID) + relay provider flags | `data.get_slide_mailbox_for_iris_subscription.threads_by_folder.edges[].node.as_ig_direct_thread` |
| `PolarisDirectMessageRequestQuery` | same, plus `__relay_internal__pv__IGD30DayAgoTimestampMsrelayprovider` | same; threads have `system_folder: "PENDING"` |
| `IGDThreadDetailQuery` | `{thread_fbid, min_uq_seq_id: null, …InitialMessagePageCount: 20}` (`thread_key` works too) | `data.get_slide_thread_nullable.as_ig_direct_thread` (`slide_messages.edges`, `users`, `viewer`, `thread_id`) |
| `IGDirectTextSendMutation` | `{ig_thread_igid: <thread_fbid>, offline_threading_id, text: {sensitive_string_value}, reply_to_message_id, mentions: [], send_attribution: "igd_web_chat_tab:in_thread", …nulls}` | `data.xig_direct_text_send_with_slide_messaging_response.{message_id, timestamp_ms}` |
| `useIGDMarkThreadAsReadMutation` | `{metadata: {ig_thread_igid: <thread_id>}, data: {item_id: "", message_id}}` | `…item_seen_mutation_with_slide_messaging_response.watermark_timestamp_ms` |
| `useIGDirectAcceptMessageRequestMutation` | `{thread_fbid, ig_inbox_folder: null, offline_threading_id}` | `data.ig_direct_accept_message_request.{system_folder, folder}` |

Notes:
- **IDs.** Threads have three: `thread_fbid` (used by most operations), `thread_key` (the peer's messaging fbid in
  1:1 chats) and `thread_id` (a long `3402823…` legacy id, needed by *mark-seen*).
- **`offline_threading_id`** is the client-generated id: `(epoch_ms << 22) | random_22_bits`.
- **`useIGDSystemFolderUnreadThreadCountQuery`** is misleadingly named. It returned already-read threads, so it isn't
  used for unread state.

### Message content

`slide_messages.edges[].node` has `content_type` and `content.__typename`:

| content_type | `__typename` | Meaning |
|---|---|---|
| `TEXT` | `SlideMessageText` | `text_body` |
| `IMAGES` | `SlideMessageImageContent` | `attachments[].{attachment_cdn_url, preview_cdn_url, preview_width/height}` |
| `MESSAGE_INLINE_SHARE` | `SlideMessageXMAContent` | shared reel/post/story/link: `xma.{target_url, header_title_text (author), preview_image.preview_image_decoration_type}` |

A **reel** is an XMA with `target_url` `instagram.com/reel/<shortcode>/` and `preview_image_decoration_type: "REEL"`.
Posts use `/p/` and stories `/stories/`. Outgoing messages that contain a URL also come back as XMA link shares,
with the text preserved in `text_body`.

## 3. Read-only browsing (profiles, posts, stories, comments, feeds)

Same GraphQL transport. Each web page type uses its own persisted operation; `ops_catalog.json` holds each
operation's doc_id and full variable template (with the `__relay_internal__pv__*` flags the server expects), built
from captures by `tools/build_catalog.py`. Some pages make no XHR at all: their queries are preloaded in the HTML
under `"expectedPreloaders":[{"queryID","variables","queryName"}]`, which the catalog builder also reads.

| Feature | Operation (or REST) | Key variables |
|---|---|---|
| search | `PolarisSearchBoxRefetchableQuery` | `data.query`, `data.context: "blended"`, `data.search_surface: "web_top_search"`, `hasQuery` |
| profile | `PolarisProfilePageContentQuery` | `id` (user pk) |
| posts | `PolarisProfilePostsQuery`, then `PolarisProfilePostsTabContentQuery_connection` | `username`, `data.count` (>= 6), `after` |
| reels tab | `PolarisProfileReelsTabContentQuery` / `…_connection` | `user_id`/`id`, `data.target_user_id`, `after` |
| tagged | `PolarisProfileTaggedTabContentQuery` | `user_id`, `count` |
| highlights | `PolarisProfileStoryHighlightsTrayContentQuery`; items `PolarisStoriesV3HighlightsPageQuery` | `user_id`; `reel_ids: ["highlight:<id>"]` |
| stories | `PolarisStoriesV3ReelPageStandaloneQuery`; tray `PolarisStoriesV3TrayContainerQuery` | `reel_ids_arr: [<user pk>]` |
| post | `PolarisPostRootQuery` (preloaded) | `shortcode` |
| comments | `PolarisPostCommentsContainerQuery` (preloaded), then `PolarisPostCommentsPaginationQuery` | `media_id`, `after`, `sort_order` |
| replies | `PolarisPostChildCommentsQuery` | `parent_comment_id`, `after` |
| reels feed | `PolarisClipsTabDesktopPaginationQuery` | `after` |
| hashtag | `PolarisKeywordSearchExplorePageRelayQuery` | `query: "#tag"` |
| location | `PolarisLocationPageTabContentQuery` (preloaded) / `…_connection` | `location_id`, `tab: ranked\|recent`, `after` |
| likers | REST `GET /api/v1/media/<pk>/likers/` | |
| followers | REST `GET /api/v1/friendships/<pk>/followers/` (`following/`) | `count`, `max_id` |
| home feed | REST `GET /api/v1/feed/timeline/` | `max_id` |
| explore | REST `GET /api/v1/discover/web/explore_grid/` | `max_id` |
| notifications | REST `GET /api/v1/news/inbox/` | |

Observations:
- **Gone from web REST:** `users/web_profile_info` (always 429 outside Instagram's own page loads), `users/<pk>/info`,
  `feed/user/<pk>`, `media/<pk>/comments`, `web/search/topsearch`.
- **Username to pk:** the plain-HTTP profile page carries no ids; exact match in search results is reliable (works for
  private accounts too).
- **Follower lists of other people's large accounts** stop after the first page
  (`should_limit_list_of_followers: true`, no `next_max_id`), the same as on instagram.com.
- **Shortcode and media pk** are the same number: base64 over `A-Za-z0-9-_`.

## 4. Writes: actions, publishing, DMs, account

All of these were captured from instagram.com and re-sent from a script; each was verified by reading the result back.

| Feature | Operation (or endpoint) | Key inputs |
|---|---|---|
| like / unlike | `usePolarisLikeMediaXIGLikeMutation` / `…XIGUnlikeMutation` | `input: {actor_id, client_mutation_id, media_id}` |
| save / unsave | `usePolarisSaveMediaSaveMutation` / `…UnsaveMutation` | same `input` shape |
| follow / unfollow | `usePolarisFollowMutation` / `usePolarisUnfollowMutation` | `target_user_id`, `container_module` |
| comment | `PolarisPostCommentInputRevampedMutation` | `data: {comment_text, media_id}`, `root_connections: []` |
| delete comment | `usePolarisPostDeleteCommentMutation` | `input: {actor_id, comment_id, media_id}` |
| photo post | `POST /rupload_igphoto/fb_uploader_<upload_id>` (raw JPEG, `X-Instagram-Rupload-Params`), then REST `POST /api/v1/media/configure/` | `upload_id`, `caption` |
| carousel | one rupload per image, then REST `POST /api/v1/media/configure_sidecar/` (JSON) | `children_metadata: [{upload_id}]` |
| edit caption | REST `POST /api/v1/media/<pk>/edit_media/` (JSON) | `caption_text` |
| DM photo | `POST https://rupload.instagram.com/messenger_image/<uuid>?<page params>`, then `IGDirectMediaSendMutation` | `attachment_fbid`, `thread_id` |
| unsend | `IGDMessageUnsendDialogOffMsysMutation` | `message_id`, `send_data.thread_id` (long thread id) |
| react | `IGDirectReactionSendMutation` | `input: {emoji, message_id, thread_id, reaction_status: created\|deleted}` |
| share to chat | `IGDirectReelShareMutation` | `ig_media_igid`, `data.thread_id` or `data.recipient_users` |
| older messages | `IGDMessageListOffMsysQuery` | `id` (thread_fbid), `after` (cursor), `first` |
| edit profile | REST `POST /api/v1/web/accounts/edit/` (form) | `biography`, `first_name`, `username`, `chaining_enabled` |
| private / public | `useSettings2UpdateBooleanStorageMutation` | `storage_id: "account_privacy_setting"`, `value`, `callsite` |

REST writes are signed with `fb_dtsg` (the long `NA…:<n>:<ts>` variant from the page HTML) and `jazoest`.

### What a script can't do

Some actions are accepted by Instagram only from its own page JavaScript. From a script they return `null`
(or `{"payload": null}`) and nothing happens, even when the exact browser request is replayed from inside the page:

- block / unblock, restrict / unrestrict (`usePolarisBlockManyMutation`, `usePolarisUnblockMutation`, …). A web REST
  endpoint, `POST /api/v1/web/friendships/<pk>/block/`, does block, but there is no working way to undo it from a
  script, so the API leaves blocking out entirely
- deleting a post (`/api/v1/web/create/<pk>_<owner>/delete/`)
- publishing a reel (`/api/v1/media/configure_to_clips/`)

The failing endpoints answer in Meta's `for (;;);{"__ar":1,"payload":…}` envelope and carry per-request page fields
(`__dyn`, `__csr`, `__hsdp`, …) that look like request-time integrity values.

Also unavailable on the web client: editing DMs (the web menu only has Forward / Pin / Unsend), creating stories
and highlights on desktop, and muting chats (done over the Lightspeed WebSocket, which this client doesn't implement).

> **Warning:** don't probe guessed REST write endpoints with web cookies. Calls to mobile-only paths such as
> `restrict_action/...` answered with a redirect to login, and the session was logged out right after, twice.
> Only call endpoints you've seen the website use.

## 5. Realtime: Meta DGW WebSocket gateways

The page opens:
- `wss://gateway.instagram.com/ws/{lightspeed,realtime,streamcontroller,rpsignaling,mqttbypass}?x-dgw-appid=936619743392459&x-dgw-appversion=0&x-dgw-authtype=6:0&x-dgw-version=5&x-dgw-uuid=<actor id>&x-dgw-tier=prod&x-dgw-deviceid=<device uuid>`
- `wss://edge-chat.instagram.com/chat?sid=…&cid=…` (the legacy MQTT channel)

Binary frames: a 1-byte type, a 2-byte stream id, a length, then the payload. The observed types are:
- `0x0F`: stream open/request, followed by `{"code":200}`
- `0x0D`: data
- `0x0C`: ack
- `0x09`/`0x0A`: ping/pong

Lightspeed sync request (JSON inside `0x0F`):

```json
{"app_id":"936619743392459","device_id":"<uuid>","request_id":4,"type":2,
 "payload":"{\"database\":223,\"epoch_id\":0,\"failure_count\":0,\"last_applied_cursor\":\"{\\\"seq_id\\\":0}\",
             \"sync_params\":\"{\\\"user_agent\\\":\\\"WMI Web\\\",\\\"prevalidated_graphql_doc_id\\\":\\\"…\\\"}\",\"version\":-3}"}
```

Responses are base64 protobuf inside JSON.

Typing indicator (`mqttbypass`, a `0x0D` frame on topic `/ig_send_message`):

```json
{"action":"indicate_activity","activity_status":1,"client_context":"","thread_id":"<thread_fbid>"}
```

The server acks with `{"action":"item_ack","status":"ok",…}` on `/ig_send_message_response`.

Sending, reading and marking seen don't use the sockets. The client in this repo uses polling and doesn't implement
the gateway yet.
