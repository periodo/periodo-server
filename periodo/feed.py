from bleach import linkify
from feedgen.feed import FeedGenerator
from flask import url_for
from periodo import database
from periodo.utils import isoformat, build_client_url
from string import Template


def get_recent_activity():
    return database.query_db_for_all(
        """
SELECT
  event.what AS what,
  event.patch_id AS patch_id,
  event.comment_id AS comment_id,
  event.message AS message,
  event.time AS time,
  actor.id AS actor_id,
  actor.name AS actor_name,
  submitter.id AS submitter_id,
  submitter.name AS submitter_name
FROM (
  SELECT
    'submitted' AS what,
    id AS patch_id,
    NULL AS comment_id,
    NULL AS message,
    created_at AS time,
    created_by AS actor
  FROM patch_request
  UNION ALL
  SELECT
    'updated',
    id,
    NULL,
    NULL,
    updated_at,
    updated_by
  FROM patch_request
  WHERE updated_at > created_at
  UNION ALL
  SELECT
    CASE WHEN merged THEN 'merged' ELSE 'rejected' END,
    id,
    NULL,
    NULL,
    merged_at,
    merged_by
  FROM patch_request
  WHERE merged_at IS NOT NULL
  UNION ALL
  SELECT
    'commented on',
    patch_request_id,
    id,
    message,
    posted_at,
    author
  FROM patch_request_comment
) AS event
JOIN patch_request
ON event.patch_id = patch_request.id
JOIN user AS submitter
ON patch_request.created_by = submitter.id
JOIN user AS actor
ON event.actor = actor.id
ORDER BY event.time DESC, event.patch_id DESC, event.comment_id DESC
LIMIT 32"""
    )


def get_entry_id(row, patch_url):
    # Each event needs its own ID, distinct from other events on the same patch
    if row["what"] == "commented on":
        return "%s#comment-%s" % (patch_url, row["comment_id"])
    if row["what"] == "updated":
        # Only the most recent update is recorded, so distinguish by time
        return "%s#updated-%s" % (patch_url, row["time"])
    return "%s#%s" % (patch_url, row["what"])


def to_link(role):
    return Template('<a href="$id">$name</a>').substitute(role)


comment_template = Template("<p><span>$commenter $posted_at</span><br>$message</p>")


def get_content(what, who, submitter, review_patch_url, comment=None):
    content = {
        "submitted": "<p>$who submitted a proposed change:</p>",
        "updated": "<p>$who updated a change initially proposed by $submitter:</p>",
        "merged": "<p>$who merged a change initially proposed by $submitter:</p>",
        "rejected": "<p>$who rejected a change initially proposed by $submitter:</p>",
        "commented on": "<p>$who commented on a change initially proposed by $submitter:</p>",
    }.get(what, "")

    content += '<p><a href="$review_patch_url">$review_patch_url</a></p>'
    content += "<div>"
    if comment is not None:
        content += comment_template.substitute(comment)
    content += "</div>"

    return linkify(
        Template(content).substitute(
            {
                "who": to_link(who),
                "submitter": to_link(submitter),
                "review_patch_url": review_patch_url,
            }
        )
    )


def generate_activity_feed():
    feed_url = url_for("feed", _external=True)
    recent_activity = get_recent_activity()

    if len(recent_activity) == 0:
        return None

    fg = FeedGenerator()
    fg.id(feed_url)
    fg.title("PeriodO changes")
    fg.updated(isoformat(recent_activity[0]["time"]))
    fg.link(href=feed_url, rel="self")
    fg.author({"name": "PeriodO", "uri": "https://perio.do/"})

    for row in reversed(recent_activity):
        patch_url = url_for("patchrequest", id=row["patch_id"], _external=True)
        review_patch_url = build_client_url(
            page="review-patch",
            patchURL=url_for("patchrequest", id=row["patch_id"])[1:],
        )
        who_did_it = {"id": row["actor_id"], "name": row["actor_name"]}
        submitter = {"id": row["submitter_id"], "name": row["submitter_name"]}

        title = "%s %s change #%s" % (
            who_did_it["name"],
            row["what"],
            row["patch_id"],
        )

        comment = None
        if row["what"] == "commented on":
            comment = {
                "commenter": to_link(who_did_it),
                "message": row["message"],
                "posted_at": isoformat(row["time"]),
            }

        content = get_content(
            row["what"], who_did_it, submitter, review_patch_url, comment
        )

        fe = fg.add_entry()
        fe.id(get_entry_id(row, patch_url))
        fe.title(title)
        fe.updated(isoformat(row["time"]))
        fe.link(href=review_patch_url)
        fe.content(content, type="html")

    return fg.atom_str(pretty=True)
