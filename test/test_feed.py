import pytest
from collections import Counter
from urllib.parse import urlparse
from xml.etree import ElementTree

ATOM = "{http://www.w3.org/2005/Atom}"


def get_entries(client):
    res = client.get("/feed.xml")
    assert res.status_code == 200
    feed = ElementTree.fromstring(res.content)
    return [
        (entry.find(ATOM + "id").text, entry.find(ATOM + "title").text)
        for entry in feed.findall(ATOM + "entry")
    ]


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_feed_entry_ids_are_unique(
    active_user, admin_user, client, bearer_auth, load_json
):
    res = client.patch("/d/", json=load_json("test-patch-adds-items.json"))
    patch_id = int(res.headers["Location"].split("/")[-2])
    patch_url = urlparse(res.headers["Location"]).path
    client.post(patch_url + "messages", json={"message": "first comment"})
    client.post(patch_url + "messages", json={"message": "second comment"})
    client.post(
        patch_url + "merge", auth=bearer_auth("this-token-has-admin-permissions")
    )

    res = client.patch("/d/", json=load_json("test-patch-adds-items.json"))
    rejected_id = int(res.headers["Location"].split("/")[-2])
    client.post(
        urlparse(res.headers["Location"]).path + "reject",
        auth=bearer_auth("this-token-has-admin-permissions"),
    )

    entries = get_entries(client)
    ids = [entry_id for entry_id, _ in entries]
    assert [i for i, n in Counter(ids).items() if n > 1] == []

    titles = sorted(
        title for _, title in entries if title.endswith("change #%s" % patch_id)
    )
    assert titles == [
        "Super Admin merged change #%s" % patch_id,
        "Testy Testerson commented on change #%s" % patch_id,
        "Testy Testerson commented on change #%s" % patch_id,
        "Testy Testerson submitted change #%s" % patch_id,
    ]

    titles = sorted(
        title for _, title in entries if title.endswith("change #%s" % rejected_id)
    )
    assert titles == [
        "Super Admin rejected change #%s" % rejected_id,
        "Testy Testerson submitted change #%s" % rejected_id,
    ]


@pytest.mark.client_auth_token("this-token-has-normal-permissions")
def test_feed_comments_are_escaped(active_user, client, load_json):
    res = client.patch("/d/", json=load_json("test-patch-adds-items.json"))
    patch_url = urlparse(res.headers["Location"]).path
    client.post(
        patch_url + "messages",
        json={"message": "<script>alert(1)</script> costs $5 $who"},
    )

    res = client.get("/feed.xml")
    assert res.status_code == 200
    feed = ElementTree.fromstring(res.content)
    content = feed.find(ATOM + "entry").find(ATOM + "content").text
    assert "<script>" not in content
    assert "&lt;script&gt;alert(1)&lt;/script&gt; costs $5 $who" in content
