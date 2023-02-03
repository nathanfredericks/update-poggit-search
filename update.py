import typesense
import requests
from requests import JSONDecodeError
import os
from tenacity import retry, stop_after_attempt, retry_if_exception_type
from schema import Schema, And, Use, SchemaError
import logging

logging.basicConfig(
    filename='update-poggit-search.log',
    encoding='utf-8',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

client = typesense.Client({
    'api_key': os.getenv('TYPESENSE_API_KEY'),
    'nodes': [{
        'host': 'poggit-search.mcpe.fun',
        'port': '443',
        'protocol': 'https'
    }],
    'connection_timeout_seconds': 2 * 60
})


@retry(retry=retry_if_exception_type(JSONDecodeError), stop=stop_after_attempt(10))
def download_releases():
    r = requests.get('https://poggit.pmmp.io/releases.json')
    json = r.json()
    return json


plugin_schema = Schema([{
    'id': And(Use(str)),
    'name': And(Use(str)),
    'project_name': And(Use(str)),
    'tagline': And(Use(str)),
    'keywords': [And(Use(str))],
}], ignore_extra_keys=True)


def validate_releases(plugins):
    try:
        data = plugin_schema.validate(plugins)
        return data
    except SchemaError:
        return []


# Download releases
logging.debug('downloading releases...')
releases = download_releases()

# Validate releases
logging.debug('releases downloaded... validating')
validated = validate_releases(releases)

logging.debug('removing duplicates')

# Remove duplicates
done = set()
result = []
for plugin in validated:
    if plugin['name'] not in done:
        done.add(plugin['name'])
        result.append(plugin)

# Delete old collection
logging.debug('deleting old collection')
response1 = client.collections['plugins'].delete()
print(response1)

# Create new schema
logging.debug('creating new collection')
collection_schema = {
    'name': 'plugins',
    'fields': [
        {'name': 'name', 'type': 'string'},
        {'name': 'project_name', 'type': 'string'},
        {'name': 'tagline', 'type': 'string'},
        {'name': 'keywords', 'type': 'string[]'}
    ]
}

response2 = client.collections.create(collection_schema)
print(response2)

logging.debug('uploading collection to search index')
# Add releases
response3 = client.collections['plugins'].documents.import_(result, {'action': 'create'})
print(response3)