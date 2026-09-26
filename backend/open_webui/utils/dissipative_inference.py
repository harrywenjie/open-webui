"""Strict internal inference boundary, separate from ordinary chat customization."""
from __future__ import annotations

import copy
import hashlib
import json

from fastapi import HTTPException
from open_webui.utils.dissipative_model_contract_data import CONTRACT


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def reject(code):
    raise HTTPException(status_code=422, detail=code)


def accept_request(body):
    """Authenticate separately; content cannot enable request.state privileges."""
    try:
        wire = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(wire) > 512000:
            reject('INTERNAL_MODEL_INPUT_LIMIT')
        model = next((item for item in CONTRACT['registry']['models']
                      if item['workspace_model_id'] == body.get('model')), None)
        if model is None:
            reject('INTERNAL_MODEL_NOT_QUALIFIED')
        messages = body.get('messages')
        if (not isinstance(messages, list) or len(messages) != 2
            or any(set(message) != {'role', 'content'} for message in messages)
            or [message['role'] for message in messages] != ['system', 'user']
            or any(not isinstance(message['content'], str) for message in messages)):
            reject('INTERNAL_MODEL_MESSAGES_INVALID')
        prompt_hash = hashlib.sha256(messages[0]['content'].encode('utf-8')).hexdigest()
        role = next((value for value in CONTRACT['roles'].values() if value['prompt_sha256'] == prompt_hash), None)
        if role is None:
            reject('INTERNAL_MODEL_PROMPT_NOT_QUALIFIED')
        parameters = {key: value for key, value in body.items() if key not in {'model', 'messages'}}
        if digest(parameters) != role['parameters_sha256']:
            reject('INTERNAL_MODEL_PARAMETERS_NOT_QUALIFIED')
        marker = role['data_marker']
        content = messages[1]['content']
        prefix, suffix = '<' + marker + '>\n', '\n</' + marker + '>'
        if not content.startswith(prefix) or not content.endswith(suffix):
            reject('INTERNAL_MODEL_DATA_INVALID')
        if not isinstance(json.loads(content[len(prefix):-len(suffix)]), dict):
            reject('INTERNAL_MODEL_DATA_INVALID')
        return {'body': copy.deepcopy(body), 'model': copy.deepcopy(model),
                'final_sha256': digest({**body, 'model': model['provider_model_id']})}
    except (TypeError, ValueError, KeyError, AttributeError):
        reject('INTERNAL_MODEL_REQUEST_INVALID')


def validate_model(binding, model_info):
    expected = binding['model']
    if model_info is None or model_info.base_model_id != expected['base_model_id']:
        reject('INTERNAL_MODEL_ROUTE_MISMATCH')


def validate_final(binding, payload, api_config):
    if api_config.get('api_type') == 'responses' or api_config.get('azure') or api_config.get('provider') == 'azure':
        reject('INTERNAL_MODEL_TRANSPORT_NOT_QUALIFIED')
    if digest(payload) != binding['final_sha256']:
        reject('INTERNAL_MODEL_FINAL_REQUEST_MISMATCH')
