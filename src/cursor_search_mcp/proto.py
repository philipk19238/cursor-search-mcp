"""Minimal protobuf encoding for Cursor API requests."""

import gzip
import struct
from typing import Optional


def encode_varint(value: int) -> bytes:
    bits = value & 0x7F
    value >>= 7
    result = b""
    while value:
        result += bytes([0x80 | bits])
        bits = value & 0x7F
        value >>= 7
    return result + bytes([bits])


def encode_string(field_number: int, value: str) -> bytes:
    if not value:
        return b""
    encoded = value.encode("utf-8")
    tag = encode_varint((field_number << 3) | 2)  # wire type 2 = length-delimited
    length = encode_varint(len(encoded))
    return tag + length + encoded


def encode_int32(field_number: int, value: int) -> bytes:
    if value == 0:
        return b""
    tag = encode_varint((field_number << 3) | 0)  # wire type 0 = varint
    return tag + encode_varint(value)


def encode_double(field_number: int, value: Optional[float]) -> bytes:
    if value is None:
        return b""
    tag = encode_varint((field_number << 3) | 1)  # wire type 1 = 64-bit
    return tag + struct.pack("<d", float(value))


def encode_bool(field_number: int, value: bool) -> bytes:
    if not value:
        return b""
    tag = encode_varint((field_number << 3) | 0)  # wire type 0 = varint
    return tag + bytes([1])


def encode_message(field_number: int, data: bytes) -> bytes:
    if not data:
        return b""
    tag = encode_varint((field_number << 3) | 2)  # wire type 2 = length-delimited
    length = encode_varint(len(data))
    return tag + length + data


def encode_repository_info(
    repo_name: str,
    repo_owner: str,
    relative_workspace_path: str = ".",
    remote_url: Optional[str] = None,
    is_tracked: bool = True,
    is_local: bool = False,
    num_files: Optional[int] = None,
    orthogonal_transform_seed: Optional[float] = None,
    preferred_embedding_model: Optional[int] = None,
    workspace_uri: Optional[str] = None,
    preferred_db_provider: Optional[int] = None,
) -> bytes:
    result = encode_string(1, relative_workspace_path)

    if remote_url:
        result += encode_string(2, remote_url)  # remote_urls[0]
        result += encode_string(3, "origin")  # remote_names[0]

    result += encode_string(4, repo_name)
    result += encode_string(5, repo_owner)

    result += encode_bool(6, is_tracked)
    result += encode_bool(7, is_local)

    if num_files is not None:
        result += encode_int32(8, num_files)

    result += encode_double(9, orthogonal_transform_seed)

    if preferred_embedding_model is not None:
        result += encode_int32(10, preferred_embedding_model)

    if workspace_uri:
        result += encode_string(11, workspace_uri)

    if preferred_db_provider is not None:
        result += encode_int32(12, preferred_db_provider)

    return result


def encode_search_repository_request(
    query: str,
    repo_name: str,
    repo_owner: str,
    top_k: int = 10,
    rerank: bool = True,
    glob_filter: Optional[str] = None,
    remote_url: Optional[str] = None,
    is_tracked: bool = True,
    is_local: bool = False,
    num_files: Optional[int] = None,
    orthogonal_transform_seed: Optional[float] = None,
    preferred_embedding_model: Optional[int] = None,
    workspace_uri: Optional[str] = None,
    preferred_db_provider: Optional[int] = None,
) -> bytes:
    repo_info = encode_repository_info(
        repo_name=repo_name,
        repo_owner=repo_owner,
        remote_url=remote_url,
        is_tracked=is_tracked,
        is_local=is_local,
        num_files=num_files,
        orthogonal_transform_seed=orthogonal_transform_seed,
        preferred_embedding_model=preferred_embedding_model,
        workspace_uri=workspace_uri,
        preferred_db_provider=preferred_db_provider,
    )

    result = (
        encode_string(1, query) +
        encode_message(2, repo_info) +
        encode_int32(3, top_k) +
        encode_bool(5, rerank)
    )

    if glob_filter:
        result += encode_string(7, glob_filter)

    return result


def encode_sem_search_request(
    query: str,
    repo_name: str,
    repo_owner: str,
    top_k: int = 10,
    rerank: bool = True,
    glob_filter: Optional[str] = None,
    remote_url: Optional[str] = None,
    is_tracked: bool = True,
    is_local: bool = False,
    num_files: Optional[int] = None,
    orthogonal_transform_seed: Optional[float] = None,
    preferred_embedding_model: Optional[int] = None,
    workspace_uri: Optional[str] = None,
    preferred_db_provider: Optional[int] = None,
) -> bytes:
    inner = encode_search_repository_request(
        query=query,
        repo_name=repo_name,
        repo_owner=repo_owner,
        top_k=top_k,
        rerank=rerank,
        glob_filter=glob_filter,
        remote_url=remote_url,
        is_tracked=is_tracked,
        is_local=is_local,
        num_files=num_files,
        orthogonal_transform_seed=orthogonal_transform_seed,
        preferred_embedding_model=preferred_embedding_model,
        workspace_uri=workspace_uri,
        preferred_db_provider=preferred_db_provider,
    )
    return encode_message(1, inner)


def wrap_connect_envelope(data: bytes, compressed: bool = False) -> bytes:
    flags = 1 if compressed else 0
    return struct.pack(">BI", flags, len(data)) + data


def decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        result |= (byte & 0x7F) << shift
        pos += 1
        if not (byte & 0x80):
            break
        shift += 7
    return result, pos


def decode_string(data: bytes, pos: int) -> tuple[str, int]:
    length, pos = decode_varint(data, pos)
    value = data[pos:pos + length].decode("utf-8")
    return value, pos + length


def decode_connect_envelope(data: bytes) -> list[bytes]:
    messages = []
    pos = 0

    while pos < len(data):
        if pos + 5 > len(data):
            break

        flags = data[pos]
        length = struct.unpack(">I", data[pos + 1:pos + 5])[0]
        pos += 5

        if pos + length > len(data):
            break

        message = data[pos:pos + length]
        pos += length

        if flags & 0x02:
            continue

        if flags & 0x01:
            try:
                message = gzip.decompress(message)
            except Exception:
                pass

        messages.append(message)

    return messages


def parse_code_result_with_classification(data: bytes, pos: int, end: int) -> Optional[dict]:
    while pos < end:
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7

        if field_number == 1 and wire_type == 2:  # code_result
            length, pos = decode_varint(data, pos)
            item_end = pos + length
            result = parse_code_result(data, pos, item_end)
            return result

        pos = skip_field(data, pos, wire_type)

    return None


def parse_code_result(data: bytes, pos: int, end: int) -> dict:
    result = {"codeBlock": {}, "score": 0.0}

    while pos < end:
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7

        if field_number == 1 and wire_type == 2:  # code_block
            length, pos = decode_varint(data, pos)
            block_end = pos + length
            result["codeBlock"] = parse_code_block(data, pos, block_end)
            pos = block_end
        elif field_number == 2 and wire_type == 1:  # score (double)
            result["score"] = struct.unpack("<d", data[pos:pos + 8])[0]
            pos += 8
        elif field_number == 2 and wire_type == 5:  # score (float)
            result["score"] = struct.unpack("<f", data[pos:pos + 4])[0]
            pos += 4
        else:
            pos = skip_field(data, pos, wire_type)

    return result


def parse_code_block(data: bytes, pos: int, end: int) -> dict:
    result = {
        "relativeWorkspacePath": "",
        "contents": "",
        "range": {"startPosition": {}, "endPosition": {}},
        "fileContents": "",
        "overrideContents": "",
        "originalContents": "",
    }

    while pos < end:
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7

        if field_number == 1 and wire_type == 2:  # relative_workspace_path
            result["relativeWorkspacePath"], pos = decode_string(data, pos)
        elif field_number == 2 and wire_type == 2:  # file_contents
            result["fileContents"], pos = decode_string(data, pos)
        elif field_number == 3 and wire_type == 2:  # range
            length, pos = decode_varint(data, pos)
            range_end = pos + length
            result["range"] = parse_range(data, pos, range_end)
            pos = range_end
        elif field_number == 4 and wire_type == 2:  # contents
            result["contents"], pos = decode_string(data, pos)
        elif field_number == 6 and wire_type == 2:  # override_contents
            result["overrideContents"], pos = decode_string(data, pos)
        elif field_number == 7 and wire_type == 2:  # original_contents
            result["originalContents"], pos = decode_string(data, pos)
        else:
            pos = skip_field(data, pos, wire_type)

    if not result["contents"]:
        if result["overrideContents"]:
            result["contents"] = result["overrideContents"]
        elif result["fileContents"]:
            result["contents"] = result["fileContents"]
        elif result["originalContents"]:
            result["contents"] = result["originalContents"]

    return result


def parse_range(data: bytes, pos: int, end: int) -> dict:
    result = {"startPosition": {}, "endPosition": {}}

    while pos < end:
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7

        if field_number == 1 and wire_type == 2:  # start_position
            length, pos = decode_varint(data, pos)
            pos_end = pos + length
            result["startPosition"] = parse_position(data, pos, pos_end)
            pos = pos_end
        elif field_number == 2 and wire_type == 2:  # end_position
            length, pos = decode_varint(data, pos)
            pos_end = pos + length
            result["endPosition"] = parse_position(data, pos, pos_end)
            pos = pos_end
        else:
            pos = skip_field(data, pos, wire_type)

    return result


def parse_position(data: bytes, pos: int, end: int) -> dict:
    result = {"line": 0, "column": 0}

    while pos < end:
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7

        if field_number == 1 and wire_type == 0:  # line
            result["line"], pos = decode_varint(data, pos)
        elif field_number == 2 and wire_type == 0:  # column
            result["column"], pos = decode_varint(data, pos)
        else:
            pos = skip_field(data, pos, wire_type)

    return result


def skip_field(data: bytes, pos: int, wire_type: int) -> int:
    if wire_type == 0:  # varint
        while data[pos] & 0x80:
            pos += 1
        pos += 1
    elif wire_type == 1:  # 64-bit
        pos += 8
    elif wire_type == 2:  # length-delimited
        length, pos = decode_varint(data, pos)
        pos += length
    elif wire_type == 5:  # 32-bit
        pos += 4
    return pos


def parse_search_response(data: bytes) -> list[dict]:
    results = []
    pos = 0
    end = len(data)

    while pos < end:
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7

        if field_number == 1 and wire_type == 2:  # code_results (repeated) or response
            length, pos = decode_varint(data, pos)
            item_end = pos + length
            payload = data[pos:item_end]

            # Check if this is a nested response (SemSearchResponse)
            # or a direct CodeResult. Try parsing as CodeResult first.
            result = None
            try:
                result = parse_code_result(payload, 0, len(payload))
            except Exception:
                result = None

            if result and result["codeBlock"].get("relativeWorkspacePath"):
                results.append(result)
            else:
                # Might be nested response, try parsing inner
                inner_results = parse_search_response(payload)
                results.extend(inner_results)
            pos = item_end
        elif field_number == 3 and wire_type == 2:  # code_results (SemSearchResponse)
            length, pos = decode_varint(data, pos)
            item_end = pos + length
            try:
                result = parse_code_result_with_classification(data, pos, item_end)
                if result and result.get("codeBlock", {}).get("relativeWorkspacePath"):
                    results.append(result)
            except Exception:
                pass
            pos = item_end
        else:
            pos = skip_field(data, pos, wire_type)

    return results
