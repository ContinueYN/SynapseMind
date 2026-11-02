"""Domain -> HTTP mappers, split by resource.

Routes and response validation only see these DTOs. The answer store is not
reachable from here.

Import the feature module directly (for example
``synapse.api.mappers.sessions``); there is no aggregate module.
"""
