# coding: utf-8

# Copyright (c) 2015, thumbor-community
# Use of this source code is governed by the MIT license that can be
# found in the LICENSE file.

import thumbor.loaders.http_loader as http_loader
from thumbor.utils import logger
from thumbor.loaders import LoaderResult

from . import *
from ..aws.bucket import Bucket

def validate(context, url, normalize_url_func=http_loader._normalize_url):
    return _validate(context, url, normalize_url_func)

async def load(context, url):
    """
    Loads image
    :param Context context: Thumbor's context
    :param string url: Path to load
    """
    if _use_http_loader(context, url):
        return await http_loader.load(context, url, normalize_url_func=http_loader._normalize_url)

    bucket, key = _get_bucket_and_key(context, url)

    if not _validate_bucket(context, bucket):
        result = LoaderResult(successful=False,
                              error=LoaderResult.ERROR_NOT_FOUND)
        return result

    loader = Bucket(bucket, context.config.get('TC_AWS_REGION'), context.config.get('TC_AWS_ENDPOINT'))
    handle_data = HandleDataFunc.as_func(key,
                                         bucket_loader=loader,
                                         max_retry=context.config.get('TC_AWS_MAX_RETRY'))

    file_key = await loader.get(key)
    return handle_data(file_key)


class HandleDataFunc(object):

    def __init__(self, key,
                 bucket_loader=None, max_retry=0):
        self.key = key
        self.bucket_loader = bucket_loader
        self.max_retry = max_retry
        self.retries_counter = 0

    @classmethod
    def as_func(cls, *init_args, **init_kwargs):
        """
            Method to transform this class to a callback function
            that will use for getObject from s3
        """

        def handle_data(file_key):
            instance = cls(*init_args, **init_kwargs)
            instance.dispatch(file_key)

        handle_data.init_args = init_args
        handle_data.init_kwargs = init_kwargs

        return handle_data

    def __increment_retry_counter(self):
        self.retries_counter = self.retries_counter + 1

    def dispatch(self, file_key):
        """ Callback method for getObject from s3 """
        if not file_key or 'Error' in file_key or 'Body' not in file_key:

            logger.error(
                "ERROR retrieving image from S3 {0}: {1}".
                format(self.key, str(file_key)))

            # If we got here, there was a failure.
            # We will return 404 if S3 returned a 404, otherwise 502.
            result = LoaderResult()
            result.successful = False

            if not file_key:
                result.error = LoaderResult.ERROR_UPSTREAM
                return result

            response_metadata = file_key.get('ResponseMetadata', {})
            status_code = response_metadata.get('HTTPStatusCode')

            if status_code == 404:
                result.error = LoaderResult.ERROR_NOT_FOUND
                return result

            if self.retries_counter < self.max_retry:
                self.__increment_retry_counter()
                self.bucket_loader.get(self.key,
                                       callback=self.dispatch)
            else:
                result.error = LoaderResult.ERROR_UPSTREAM
                return result
        else:
            return file_key['Body'].read()
