"""
    Python Zendesk is wrapper for the Zendesk API. This library provides an
    easy and flexible way for developers to communicate with their Zendesk
    account in their application.

    Notes:
    API THROTTLE is not handled in this library:
        From Zendesk: The throttle will be applied once an API consumer
        reaches a certain threshold in terms of a maximum of requests per
        minute. Most clients will never hit this threshold, but those that do,
        will get met by a HTTP 503 response code and a text body of
        "Number of allowed API requests per minute exceeded"

    TICKETS AS AN END-USER is not handled in this library:
        There are a number of API calls for working with helpdesk tickets as
        if you were the person (end-user) who originally created them. At the
        moment, this library is primarily for admins and agents to interact

    FORUMS, ENTRIES, POSTS have not yet been implemented

"""

__author__ = "Max Gutman <max@eventbrite.com>"
__version__ = "1.1.1"

import re
import httplib2
import urllib
import base64
try:
    import simplejson as json
except:
    import json
from httplib import responses
from endpoints import mapping_table as mapping_table_v1
from endpoints_v2 import mapping_table as mapping_table_v2

V2_COLLECTION_PARAMS = [
        'page',
        'per_page',
        'sort_order',
        'sort_by'
    ]

class ZendeskError(Exception):
    def __init__(self, msg, code, response):
        self.msg = msg
        self.error_code = code
        self.response = response

    def __str__(self):
        return repr('%s: %s %s' % (self.error_code, self.msg, self.response))


class AuthenticationError(ZendeskError):
    pass


class RateLimitError(ZendeskError):
    pass

re_identifier = re.compile(r".*/(?P<identifier>\d+)\.(json|xml)")


def get_id_from_url(url):
    match = re_identifier.match(url)
    if match and match.group('identifier'):
        return match.group('identifier')


def clean_kwargs(kwargs):
    """Format the kwargs to conform to API"""

    for key, value in kwargs.iteritems():
        if hasattr(value, '__iter__') and type(value) is not str:
            kwargs[key] = ','.join(map(str, value))


class Zendesk(object):
    """ Python API Wrapper for Zendesk"""

    def __init__(self, zendesk_url, zendesk_username,
                 zendesk_password=None, use_api_token=False, headers=None,
                 client_args={}, api_version=1):
        """
        Instantiates an instance of Zendesk. Takes optional parameters for
        HTTP Basic Authentication

        Parameters:
        zendesk_url - https://company.zendesk.com (use http if not SSL enabled)
        zendesk_username - Specific to your Zendesk account (typically email)
        zendesk_password - Specific to your Zendesk account or your account's
            API token if use_api_token is True
        use_api_token - use api token for authentication instead of user's
            actual password
        headers - Pass headers in dict form. This will override default.
        client_args - Pass arguments to http client in dict form.
            {'cache': False, 'timeout': 2}
            or a common one is to disable SSL certficate validation
            {"disable_ssl_certificate_validation": True}
        """
        self.data = None

        # Set attributes necessary for API
        self.zendesk_url = zendesk_url.rstrip('/')
        self.zendesk_username = zendesk_username
        if use_api_token:
            self.zendesk_username += "/token"
        self.zendesk_password = zendesk_password

        # Set headers
        self.headers = headers
        if self.headers is None:
            self.headers = {
                'User-agent': 'Zendesk Python Library v%s' % __version__,
                'Content-Type': 'application/json'
            }

        # Set http client and authentication
        self.client = httplib2.Http(**client_args)
        if (self.zendesk_username is not None and
                self.zendesk_password is not None):
            self.client.add_credentials(
                self.zendesk_username,
                self.zendesk_password
            )
            self.headers["Authorization"] = "Basic %s" % (
                 base64.b64encode(self.zendesk_username + ':' +
                                  self.zendesk_password))
        self.api_version = api_version
        if self.api_version == 1:
            self.mapping_table = mapping_table_v1
        elif self.api_version == 2:
            self.mapping_table = mapping_table_v2
        else:
            raise ValueError("Unsupported Zendesk API Version: %d" %
                             (self.api_version,))

    def __getattr__(self, api_call):
        """
        Instead of writing out each API endpoint as a method here or
        binding the API endpoints at instance runttime, we can simply
        use an elegant Python technique to construct method execution on-
        demand. We simply provide a mapping table between Zendesk API calls
        and function names (with necessary parameters to replace
        embedded keywords on GET or json data on POST/PUT requests).

        __getattr__() is used as callback method implemented so that
        when an object tries to call a method which is not defined here,
        it looks to find a relationship in the the mapping table.  The
        table provides the structure of the API call and parameters passed
        in the method will populate missing data.

        TODO:
            Should probably url-encode GET query parameters on replacement
        """
        def call(self, **kwargs):
            """ """
            api_map = self.mapping_table[api_call]
            path = api_map['path']
            if self.api_version == 2:
                path = "/api/v2" + path

            method = api_map['method']
            status = api_map['status']
            valid_params = api_map.get('valid_params', ())
            # Body can be passed from data or in args
            body = kwargs.pop('data', None) or self.data
            # If requested, return all response information
            complete_response = kwargs.pop('complete_response', False)
            # Support specifying a mime-type other than application/json
            mime_type = kwargs.pop('mime_type', 'application/json')
            # Substitute mustache placeholders with data from keywords
            url = re.sub(
                '\{\{(?P<m>[a-zA-Z_]+)\}\}',
                # Optional pagination parameters will default to blank
                lambda m: "%s" % kwargs.pop(m.group(1), ''),
                self.zendesk_url + path
            )
            # Validate remaining kwargs against valid_params and add
            # params url encoded to url variable.
            for kw in kwargs:
                if (kw not in valid_params and
                        (self.api_version == 2 and
                         kw not in V2_COLLECTION_PARAMS)):
                    raise TypeError("%s() got an unexpected keyword argument "
                                    "'%s'" % (api_call, kw))
            else:
                clean_kwargs(kwargs)
                url += '?' + urllib.urlencode(kwargs)

            if mime_type == "application/json":
                body = json.dumps(body)
                self.headers["Content-Type"] = "application/json"
            else:
                self.headers["Content-Type"] = mime_type

            # Make an http request (data replacements are finalized)
            response, content = \
                self.client.request(
                    url,
                    method,
                    body=body,
                    headers=self.headers
                )
            # Use a response handler to determine success/fail
            return self._response_handler(response, content, status,
                complete_response)

        # Missing method is also not defined in our mapping table
        if api_call not in self.mapping_table:
            raise AttributeError('Method "%s" Does Not Exist' % api_call)

        # Execute dynamic method and pass in keyword args as data to API call
        return call.__get__(self)

    @staticmethod
    def _response_handler(response, content, status, complete_response=False):
        """
        Handle response as callback

        If the response status is different from status defined in the
        mapping table, then we assume an error and raise proper exception

        Zendesk's response is sometimes the url of a newly created user/
        ticket/group/etc and they pass this through 'location'.  Otherwise,
        the body of 'content' has our response.
        """
        response_status = int(response.get('status', 0))

        if response_status != status:
            if response_status == 401:
                raise AuthenticationError(content, response_status, response)
            elif response_status == 429:
                raise RateLimitError(content, response_status, response)
            else:
                raise ZendeskError(content, response_status, response)

        if complete_response:
            if content.strip():
                content = json.loads(content)

            return {
                'response': response,
                'content': content,
                'status': status
            }

        # Deserialize json content if content exist. In some cases Zendesk
        # returns ' ' strings. Also return false non strings (0, [], (), {})
        # if response.get('location'):
        #     return response.get('location')
        # elif content.strip():
        #     return json.loads(content)
        # else:
        #     return responses[response_status]

        # re-order logic. creating an attachment returns location and json
        # but in the old logic was only returning the url this way. We 
        # want the json!
        if content.strip():
            return json.loads(content)
        elif response.get('location'):
            return response.get('location')
        else:
            return responses[response_status]
