namespaces = {
    'dbpedia': 'http://dbpedia.org/resource/',
    'dcelements': 'https://staging.perio.do/zmdxzf369.ttl.html',
    'dcterms': 'http://purl.org/dc/terms/',
    'foaf': 'http://xmlns.com/foaf/0.1/',
    'owl': 'http://www.w3.org/2002/07/owl#',
    'skos': 'http://www.w3.org/2004/02/skos/core#',
    'time': 'http://www.w3.org/2006/time#',
    'void': 'http://rdfs.org/ns/void#',
}


def bind(graph):
    for prefix, ns in namespaces.items():
        graph.bind(prefix, ns)
