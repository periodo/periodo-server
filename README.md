# PeriodO Server

A web server for serving and accepting patches for [PeriodO](http://perio.do/) data.


# Setup

Running `make` by itself will install required packages, initialize the database if it does not yet exist, and generate the RDF representing the vocabulary terms and SHACL shapes used in PeriodO data.

## Serving the browser client application

If running on a production server, after running `make`, you will want to run `make fetch_latest_client`, which will download the latest version of the [PeriodO browser client](https://github.com/periodo/periodo-client) and unpack it into a directory that will be served for `text/html` requests to the server.

If you are working on the client, and want to see your changes reflected from responses from this server, you should run the command `make link_client_repostiory`. As with the validation repository described above, this command assumes that the periodo-client code is in a directory that is a sibling to this one, named `periodo-client`. If it is elsewhere, you will need add `CLIENT_REPO=...(path to client)...`.

## Working with bags

You can create a "bag" of definition URIs by sending an authenticated `PUT` request to `http://n2t.net/ark:/99152/p0bags/[UUID]`, where `[UUID]` is a [UUID (universally unique identifier)](https://en.wikipedia.org/wiki/Universally_unique_identifier) that you generate. The body of the request should be a JSON object with at least the keys `title` and `items`. The value of the `items` key must be either a list of PeriodO period identifiers, or an objects with PeriodO period identifiers as keys:

```bash
$ export BAG_UUID=$(uuid)
$ export AUTH_TOKEN=$(get_token_somehow)
$ curl -L -X PUT\
  -H "Authorization: Bearer $AUTH_TOKEN"
  -H "Content-Type: application/json"\
  -d '{"title": "my bag of periods", "items": ["p03377fkhrv", "p0d39r7d5km"]}'\
  "http://n2t.net/ark:/99152/p0bags/$BAG_UUID"
```

A `GET` request for a bag returns a JSON-LD representation including the full details of the bag's period definitions:

```bash
$ curl -L -X GET "http://n2t.net/ark:/99152/p0bags/$BAG_UUID" | jq .
```
```json
{
  "@context": { ... },
  "@id": "p0bags/...",
  "creator": "http://orcid.org/...",
  "title": "my bag of periods",
  "items": {
    "p03377fkhrv": { ... full JSON-LD for period definition ... },
    "p0d39r7d5km": { ... full JSON-LD for period definition ... }
    }
  }
}
```

Bags are versioned. When initially created a bag has version `0`. Subsequent `PUT`s to a bag URL will increment the version. `GET` requests can be made for specific versions by appending a `version` query parameter. Bags also support [conditional requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Conditional_requests) using [`Etag`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/ETag) headers.
