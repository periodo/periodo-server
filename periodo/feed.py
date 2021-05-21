from bleach import linkify
from collections import defaultdict
from feedgen.feed import FeedGenerator
from flask import url_for
from periodo import database
from periodo.utils import isoformat, build_client_url
from string import Template


def get_recent_activity():
    return database.query_db_for_all(
        """
SELECT
  patch_request.id AS id,
  patch_request.open AS open,
  patch_request.merged AS merged,
  patch_request.created_at AS created_at,
  creator.id AS creator_id,
  creator.name AS creator_name,
  patch_request.updated_at AS updated_at,
  updater.id AS updater_id,
  updater.name AS updater_name,
  patch_request.merged_at AS merged_at,
  merger.id AS merger_id,
  merger.name AS merger_name,
  comment.posted_at AS posted_at,
  commenter.id AS commenter_id,
  commenter.name AS commenter_name,
  comment.message AS message,
  MAX(
    patch_request.created_at,
    patch_request.updated_at,
    IFNULL(patch_request.merged_at, 0),
    IFNULL(comment.posted_at, 0)
  ) AS last_update_time
FROM patch_request
JOIN user AS creator
ON patch_request.created_by = creator.id
JOIN user AS updater
ON patch_request.updated_by = updater.id
LEFT JOIN user AS merger
ON patch_request.merged_by = merger.id
LEFT JOIN patch_request_comment AS comment
ON patch_request.id = comment.patch_request_id
LEFT JOIN user AS commenter
ON comment.author = commenter.id
ORDER BY last_update_time
DESC LIMIT 32"""
    )


def get_roles(row):
    return {
        "submitter": {
            "id": row["creator_id"],
            "name": row["creator_name"],
        },
        "updater": {
            "id": row["updater_id"],
            "name": row["updater_name"],
        },
        "merger": {
            "id": row["merger_id"],
            "name": row["merger_name"],
        },
        "commenter": {
            "id": row["commenter_id"],
            "name": row["commenter_name"],
        },
    }


def get_what_happened(row):
    if row["open"]:
        if row["updated_at"] > row["created_at"]:
            what_happened = "updated"
        else:
            what_happened = "submitted"
    elif row["merged"]:
        what_happened = "merged"
    else:
        what_happened = "rejected"
    if row["last_update_time"] == row["posted_at"]:
        what_happened = "commented on"

    return what_happened


def get_who_did_it(what_happened, roles):
    return {
        "submitted": roles["submitter"],
        "updated": roles["updater"],
        "merged": roles["merger"],
        "rejected": roles["merger"],
        "commented on": roles["commenter"],
    }.get(what_happened)


def to_link(role):
    return Template('<a href="$id">$name</a>').substitute(role)


comment_template = Template("<p><span>$commenter $posted_at</span><br>$message</p>")


def get_content(what, who, submitter, review_patch_url, comments):
    content = {
        "submitted": "<p>$who submitted a proposed change:</p>",
        "updated": "<p>$who updated a change initially proposed by $submitter:</p>",
        "merged": "<p>$who merged a change initially proposed by $submitter:</p>",
        "rejected": "<p>$who rejected a change initially proposed by $submitter:</p>",
        "commented on": "<p>$who commented on a change initially proposed by $submitter:</p>",
    }.get(what, "")

    content += '<p><a href="$review_patch_url">$review_patch_url</a></p>'
    content += "<div>"
    content += "".join([comment_template.substitute(comment) for comment in comments])
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
    fg.updated(isoformat(recent_activity[0]["last_update_time"]))
    fg.link(href=feed_url, rel="self")
    fg.author({"name": "PeriodO", "uri": "https://perio.do/"})

    comments = defaultdict(list)

    for row in reversed(recent_activity):
        patch_url = url_for("patchrequest", id=row["id"], _external=True)
        review_patch_url = build_client_url(
            page="review-patch", patchURL=url_for("patchrequest", id=row["id"])[1:]
        )
        roles = get_roles(row)
        what_happened = get_what_happened(row)
        who_did_it = get_who_did_it(what_happened, roles)

        title = "%s %s change #%s" % (
            who_did_it["name"],
            what_happened,
            row["id"],
        )

        if row["message"] is not None:
            comments[row["id"]].append(
                {
                    "commenter": to_link(roles["commenter"]),
                    "message": row["message"],
                    "posted_at": isoformat(row["posted_at"]),
                }
            )

        content = get_content(
            what_happened,
            who_did_it,
            roles["submitter"],
            review_patch_url,
            comments[row["id"]],
        )

        fe = fg.add_entry()
        fe.id(patch_url)
        fe.title(title)
        fe.updated(isoformat(row["last_update_time"]))
        fe.link(href=review_patch_url)
        fe.content(content, type="html")

    return fg.atom_str(pretty=True)
