"""Redis-backed conversation store, generalised from FIN + SMN.

Messages are EPHEMERAL by design (TTL per message); Postgres only holds the
durable artifacts (blocks, see models.py). This is the architecture proven in
production twice: SendMeNow (24h TTL, free-form pairs) and FindItNow (7-day
TTL, item-scoped pairs). The template keeps the layout and generalises:

  - participants: any 2+ user ids (not owner/finder);
  - ``ref``: optional external anchor ("item:42:finder:7", "order:9"...) used
    to idempotently reuse the same conversation for the same context;
  - ``msg_type``: "text" by default; media types ("photo", "video", "audio")
    carry a URL in ``content`` (see the voice_messages template for audio);
  - TTL configurable via ``REALTIME_MESSAGING_TTL_SECONDS`` (default 7 days).

Redis layout (one DB, ideally the ephemeral one of redis_dual_db.py):
    rtm:conv:<uuid>        HSET  conversation metadata (participants, ref)
    rtm:msg:<uuid>         HSET  single message (TTL)
    rtm:msgs:<conv_uuid>   ZSET  message UUIDs scored by timestamp
    rtm:user:<user_id>     SET   conv UUIDs the user participates in
    rtm:ref:<ref>          STR   conv UUID lookup for idempotent reuse
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone


def ttl_seconds() -> int:
    return int(getattr(settings, "REALTIME_MESSAGING_TTL_SECONDS", 7 * 24 * 3600))


def redis_url() -> str:
    """First configured URL wins; empty string means the store is dormant."""
    for name in ("REALTIME_MESSAGING_REDIS_URL", "REDIS_EPHEMERAL_URL", "REDIS_URL"):
        url = getattr(settings, name, "") or ""
        if url:
            return url
    import os

    return os.environ.get("REALTIME_MESSAGING_REDIS_URL", "") or os.environ.get("REDIS_URL", "")


_client = None


def get_redis():
    """Lazy singleton. Raises RuntimeError when no Redis is configured: the
    views translate that into a 503 "dormant" instead of a 500."""
    global _client
    if _client is None:
        url = redis_url()
        if not url:
            raise RuntimeError("realtime_messaging: aucun Redis configure (REALTIME_MESSAGING_REDIS_URL / REDIS_URL)")
        import redis

        _client = redis.Redis.from_url(url, decode_responses=True)
    return _client


def set_client_for_tests(client) -> None:
    """Inject a fake client (tests) or reset with None."""
    global _client
    _client = client


def _k_conv(cid: str) -> str:
    return f"rtm:conv:{cid}"


def _k_msg(mid: str) -> str:
    return f"rtm:msg:{mid}"


def _k_msgs(cid: str) -> str:
    return f"rtm:msgs:{cid}"


def _k_user(uid) -> str:
    return f"rtm:user:{uid}"


def _k_ref(ref: str) -> str:
    return f"rtm:ref:{ref}"


# --- conversations ----------------------------------------------------------

def create_or_get_conversation(*, participant_ids, ref: str | None = None) -> tuple[str, bool]:
    """Idempotent when ``ref`` is given. Returns (conv_id, created)."""
    r = get_redis()
    participants = sorted({str(p) for p in participant_ids})
    if len(participants) < 2:
        raise ValueError("une conversation exige au moins 2 participants")
    if ref:
        existing = r.get(_k_ref(ref))
        if existing:
            return existing, False
    cid = str(uuid.uuid4())
    pipe = r.pipeline()
    pipe.hset(_k_conv(cid), mapping={
        "participants": json.dumps(participants),
        "ref": ref or "",
        "created_at": timezone.now().isoformat(),
    })
    if ref:
        pipe.set(_k_ref(ref), cid)
    for p in participants:
        pipe.sadd(_k_user(p), cid)
    pipe.execute()
    return cid, True


def get_conversation(cid: str) -> Optional[dict]:
    data = get_redis().hgetall(_k_conv(cid))
    if not data:
        return None
    return {
        "id": cid,
        "participants": json.loads(data.get("participants", "[]")),
        "ref": data.get("ref", ""),
        "created_at": data.get("created_at", ""),
    }


def user_is_participant(cid: str, user_id) -> bool:
    conv = get_conversation(cid)
    return bool(conv) and str(user_id) in conv["participants"]


def other_participants(cid: str, user_id) -> list[str]:
    conv = get_conversation(cid)
    if not conv:
        return []
    uid = str(user_id)
    return [p for p in conv["participants"] if p != uid]


# --- messages ----------------------------------------------------------------

def add_message(
    *,
    conv_id: str,
    sender_id,
    content: str,
    msg_type: str = "text",
    duration: int | None = None,
    reply_to_id: str | None = None,
) -> dict:
    """Append a message. ``duration`` (seconds) only means something for audio.
    Returns the hydrated message."""
    r = get_redis()
    mid = str(uuid.uuid4())
    now = timezone.now()
    ttl = ttl_seconds()
    mapping = {
        "conversation_id": conv_id,
        "sender_id": str(sender_id),
        "content": content,
        "msg_type": msg_type,
        "is_read": "0",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
        "reactions": "{}",
    }
    if duration is not None:
        mapping["duration"] = str(int(duration))
    if reply_to_id:
        replied = r.hgetall(_k_msg(reply_to_id))
        if replied:
            mapping["reply_to_id"] = reply_to_id
            mapping["reply_to_content"] = replied.get("content", "")[:200]
            mapping["reply_to_sender"] = replied.get("sender_id", "")
            mapping["reply_to_type"] = replied.get("msg_type", "text")
    pipe = r.pipeline()
    pipe.hset(_k_msg(mid), mapping=mapping)
    pipe.expire(_k_msg(mid), ttl)
    pipe.zadd(_k_msgs(conv_id), {mid: now.timestamp()})
    pipe.execute()
    return _hydrate(mid, mapping, ttl)


def _hydrate(mid: str, data: dict, ttl: int) -> dict:
    out = {
        "id": mid,
        "conversation_id": data.get("conversation_id", ""),
        "sender_id": data.get("sender_id", ""),
        "content": data.get("content", ""),
        "msg_type": data.get("msg_type", "text"),
        "is_read": data.get("is_read") == "1",
        "is_edited": data.get("is_edited") == "1",
        "created_at": data.get("created_at", ""),
        "expires_in": max(int(ttl), 0),
        "reactions": json.loads(data.get("reactions") or "{}"),
    }
    if data.get("duration"):
        out["duration"] = int(data["duration"])
    if data.get("reply_to_id"):
        out["reply_to"] = {
            "id": data["reply_to_id"],
            "content": data.get("reply_to_content", ""),
            "sender_id": data.get("reply_to_sender", ""),
            "msg_type": data.get("reply_to_type", "text"),
        }
    return out


def get_message(mid: str) -> dict | None:
    r = get_redis()
    data = r.hgetall(_k_msg(mid))
    if not data:
        return None
    ttl = r.ttl(_k_msg(mid))
    if ttl is not None and ttl <= 0:
        return None
    return _hydrate(mid, data, ttl or 0)


def list_messages(conv_id: str) -> list[dict]:
    r = get_redis()
    out = []
    for mid in r.zrange(_k_msgs(conv_id), 0, -1):
        data = r.hgetall(_k_msg(mid))
        if not data:
            continue
        ttl = r.ttl(_k_msg(mid))
        if ttl is not None and ttl <= 0:
            continue
        out.append(_hydrate(mid, data, ttl or 0))
    return out


def delete_message(mid: str, sender_id) -> str | None:
    """Only the sender deletes. Returns the conversation id, or None."""
    r = get_redis()
    data = r.hgetall(_k_msg(mid))
    if not data or data.get("sender_id") != str(sender_id):
        return None
    cid = data.get("conversation_id", "")
    pipe = r.pipeline()
    pipe.delete(_k_msg(mid))
    if cid:
        pipe.zrem(_k_msgs(cid), mid)
    pipe.execute()
    return cid


def mark_conversation_read(conv_id: str, reader_id) -> int:
    r = get_redis()
    reader = str(reader_id)
    count = 0
    for mid in r.zrange(_k_msgs(conv_id), 0, -1):
        key = _k_msg(mid)
        data = r.hgetall(key)
        if data and data.get("sender_id") != reader and data.get("is_read") == "0":
            r.hset(key, "is_read", "1")
            count += 1
    return count


def toggle_reaction(mid: str, user_id, emoji: str) -> dict | None:
    r = get_redis()
    key = _k_msg(mid)
    if not r.exists(key):
        return None
    reactions = json.loads(r.hget(key, "reactions") or "{}")
    users = reactions.get(emoji, [])
    uid = str(user_id)
    if uid in users:
        users.remove(uid)
    else:
        users.append(uid)
    if users:
        reactions[emoji] = users
    else:
        reactions.pop(emoji, None)
    r.hset(key, "reactions", json.dumps(reactions))
    return reactions


def list_user_conversations(user_id) -> list[dict]:
    """Conversations with at least one live message, recent first, with the
    last message and the unread count (the inbox screen in one call)."""
    r = get_redis()
    uid = str(user_id)
    out = []
    for cid in r.smembers(_k_user(uid)):
        conv = get_conversation(cid)
        if not conv:
            continue
        last_ids = r.zrevrange(_k_msgs(cid), 0, 0)
        if not last_ids:
            continue
        last = get_message(last_ids[0])
        if not last:
            continue
        unread = 0
        for mid in r.zrange(_k_msgs(cid), 0, -1):
            key = _k_msg(mid)
            sender = r.hget(key, "sender_id")
            if sender and sender != uid and r.hget(key, "is_read") == "0":
                unread += 1
        conv["last_message"] = last
        conv["unread_count"] = unread
        out.append(conv)
    out.sort(key=lambda c: c["last_message"]["created_at"], reverse=True)
    return out
