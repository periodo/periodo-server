namespaces = {
    'dcterms': 'http://purl.org/dc/terms/',
    'skos': 'http://www.w3.org/2004/02/skos/core#',
    'time': 'http://www.w3.org/2006/time#',
    'foaf': 'http://xmlns.com/foaf/0.1/',
    'owl': 'http://www.w3.org/2002/07/owl#',
    'void': 'http://rdfs.org/ns/void#',
    'dbpedia': 'http://dbpedia.org/resource/'
}


def bind(graph):
    for prefix, ns in namespaces.items():
        graph.bind(prefix, ns)
