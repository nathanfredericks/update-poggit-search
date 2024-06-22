import typesense
import requests
from requests import JSONDecodeError
import os
from tenacity import retry, stop_after_attempt, retry_if_exception_type
from schema import Schema, And, Use, SchemaError
import logging
from dotenv import set_key
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

client = typesense.Client({
    'api_key': os.getenv('TYPESENSE_API_KEY'),
    'nodes': [{
        'host': os.getenv('TYPESENSE_HOST'),
        'port': os.getenv('TYPESENSE_PORT'),
        'protocol': os.getenv('TYPESENSE_PROTOCOL')
    }],
    'connection_timeout_seconds': 2 * 60
})

@retry(retry=retry_if_exception_type(JSONDecodeError), stop=stop_after_attempt(10))
def download_releases():
    r = requests.get(f"{os.getenv('POGGIT_PROTOCOL')}://{os.getenv('POGGIT_HOST')}:{os.getenv('POGGIT_PORT')}/releases.min.json")
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

# Delete old collection
logging.debug('deleting old collection')
try:
    client.collections['plugins'].delete()
except Exception as e:
    pass

# Create new schema
logging.debug('creating new collection')
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

logging.debug('uploading collection to search index')

# Add releases
client.collections['plugins'].documents.import_(result, {'action': 'create'})

keys = client.keys.retrieve()['keys']

if not len(keys):
    try:
        logging.debug("creating new search key")
        key = client.keys.create({
            "description": "Search-only plugins key.",
            "actions": ["documents:search"],
            "collections": ["plugins"]
        })
        value = key['value']

        logging.debug("saving new search key to ./shared/.env.local")
        env_file_path = Path("./shared/.env.local")
        env_file_path.touch()
        set_key(dotenv_path=env_file_path, key_to_set="NEXT_PUBLIC_POGGIT_SEARCH_API_KEY", value_to_set=value)
    except Exception as e:
        logging.error(e)
        pass

