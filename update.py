import typesense
import requests
from requests import JSONDecodeError
import os
from tenacity import retry, stop_after_attempt, retry_if_exception_type
from schema import Schema, And, Use, SchemaError
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

client = typesense.Client({
    'api_key': os.getenv('TYPESENSE_API_KEY'),
    'nodes': [{
        'host': os.getenv('TYPESENSE_HOST', 'typesense'),
        'port': os.getenv('TYPESENSE_PORT', '8108'),
        'protocol': os.getenv('TYPESENSE_PROTOCOL', 'http')
    }],
})

@retry(retry=retry_if_exception_type(JSONDecodeError), stop=stop_after_attempt(10))
def download_releases():
    r = requests.get(f"{os.getenv('POGGIT_PROTOCOL', 'https')}://{os.getenv('POGGIT_HOST', 'poggit.pmmp.io')}:{os.getenv('POGGIT_PORT', '443')}/releases.min.json")
    json = r.json()
    return json


plugin_schema = Schema([{
    'id': And(Use(str)),
    'name': And(Use(str)),
    'tagline': And(Use(str)),
    'keywords': [And(Use(str))],
    'downloads': And(Use(int)),
    'version': And(Use(str)),
    'submission_date': And(Use(int)),
    'html_url': And(Use(str)),
}], ignore_extra_keys=True)


def validate_releases(plugins):
    try:
        data = plugin_schema.validate(plugins)
        return data
    except SchemaError:
        return []

logging.debug('Downloading releases from Poggit...')
releases = download_releases()

logging.debug('Validating releases...')
validated = validate_releases(releases)

logging.debug('Removing duplicate releases...')
done = set()
result = []
for plugin in validated:
    # Checks that the plugin has not been seen yet
    if plugin['name'] not in done:
        # Add it to the seen set
        done.add(plugin['name'])
        # Append the plugin to the result array
        result.append(plugin)
    # If the plugin has been seen, do this
    else:
        # Enumerate through all seen plugins
        for index, old_plugin in enumerate(result):
            # Check if plugin has the same name as plugin in results
            if old_plugin['name'] == plugin['name']:
                # Compare submission date to find newest version
                if old_plugin['submission_date'] < plugin['submission_date']:
                    # Remove old plugin and add new one
                    result.remove(old_plugin)
                    result.append(plugin)

logging.debug('Deleting previous collection...')
try:
    client.collections['plugins'].delete()
except Exception as e:
    pass

logging.debug('Creating collection...')
collection_schema = {
    'name': 'plugins',
    'fields': [
        {'name': 'name', 'type': 'string'},
        {'name': 'tagline', 'type': 'string'},
        {'name': 'keywords', 'type': 'string[]'},
        {'name': 'downloads', 'type': 'int32'},
        {'name': 'version', 'type': 'string'},
        {'name': 'submission_date', 'type': 'int64'},
        {'name': 'html_url', 'type': 'string'}
    ],
    'default_sorting_field': 'downloads'
}
client.collections.create(collection_schema)

logging.debug('Importing releases to collection...')
client.collections['plugins'].documents.import_(result, {'action': 'create'})