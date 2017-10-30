# PeriodO Server

A web server for serving and accepting patches for [PeriodO](http://perio.do/) data.


# Setup

Before running the PeriodO server, you will need to clone the [PeriodO validation](https://github.com/periodo/periodo-validation) repository. It is assumed that this project will be located in a sibling directory to this one. (That is, if this project is in `/home/patrick/Code/periodo-server`, then it is expected that the validation project is in `/home/patrick/Code/periodo-validation`). If it is elsewhere, you will need to add `VALIDATION_REPO=...(your path)...` to invocations of `make`.

Running `make` by itself will install required packages, initialize the database if it does not yet exist, and generate the RDF representing the vocabulary terms and SHACL shapes used in PeriodO data.

## Serving the browser client application

If running on a production server, after running `make`, you will want to run `make fetch_latest_client`, which will download the latest version of the [PeriodO browser client](https://github.com/periodo/periodo-client) and unpack it into a directory that will be served for `text/html` requests to the server.

If you are working on the client, and want to see your changes reflected from responses from this server, you should run the command `make link_client_repostiory`. As with the validation repository described above, this command assumes that the periodo-client code is in a directory that is a sibling to this one, named `periodo-client`. If it is elsewhere, you will need add `CLIENT_REPO=...(path to client)...`.
