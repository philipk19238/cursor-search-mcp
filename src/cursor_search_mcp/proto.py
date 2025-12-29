"""Minimal protobuf encoding for Cursor API requests.

This provides manual protobuf encoding without requiring generated code.
Based on the proto definitions from cursor-rpc.
"""

import struct
from typing import Optional


def encode_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    bits = value & 0x7F
    value >>= 7
    result = b""
    while value:
        result += bytes([0x80 | bits])
        bits = value & 0x7F
        value >>= 7
    return result + bytes([bits])


def encode_string(field_number: int, value: str) -> bytes:
    """Encode a string field."""
    if not value:
        return b""
    encoded = value.encode("utf-8")
    tag = encode_varint((field_number << 3) | 2)  # wire type 2 = length-delimited
    length = encode_varint(len(encoded))
    return tag + length + encoded


def encode_int32(field_number: int, value: int) -> bytes:
    """Encode an int32 field."""
    if value == 0:
        return b""
    tag = encode_varint((field_number << 3) | 0)  # wire type 0 = varint
    return tag + encode_varint(value)


def encode_bool(field_number: int, value: bool) -> bytes:
    """Encode a bool field."""
    if not value:
        return b""
    tag = encode_varint((field_number << 3) | 0)  # wire type 0 = varint
    return tag + bytes([1])


def encode_message(field_number: int, data: bytes) -> bytes:
    """Encode a nested message field."""
    if not data:
        return b""
    tag = encode_varint((field_number << 3) | 2)  # wire type 2 = length-delimited
    length = encode_varint(len(data))
    return tag + length + data


def encode_repository_info(
    repo_name: str,
    repo_owner: str,
    relative_workspace_path: str = ".",
) -> bytes:
    """Encode a RepositoryInfo message.

    message RepositoryInfo {
        string relative_workspace_path = 1;
        string repo_name = 4;
        string repo_owner = 5;
    }
    """
    return (
        encode_string(1, relative_workspace_path) +
        encode_string(4, repo_name) +
        encode_string(5, repo_owner)
    )


def encode_search_repository_request(
    query: str,
    repo_name: str,
    repo_owner: str,
    top_k: int = 10,
    rerank: bool = True,
    glob_filter: Optional[str] = None,
) -> bytes:
    """Encode a SearchRepositoryRequest message.

    message SearchRepositoryRequest {
        string query = 1;
        RepositoryInfo repository = 2;
        int32 top_k = 3;
        ModelDetails model_details = 4;
        bool rerank = 5;
        optional string glob_filter = 7;
    }
    """
    repo_info = encode_repository_info(repo_name, repo_owner)

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
) -> bytes:
    """Encode a SemSearchRequest message.

    message SemSearchRequest {
        SearchRepositoryRequest request = 1;
    }
    """
    inner = encode_search_repository_request(
        query=query,
        repo_name=repo_name,
        repo_owner=repo_owner,
        top_k=top_k,
        rerank=rerank,
        glob_filter=glob_filter,
    )
    return encode_message(1, inner)


def wrap_connect_envelope(data: bytes, compressed: bool = False) -> bytes:
    """Wrap data in a Connect protocol envelope.

    Format:
    - 1 byte: flags (0 = uncompressed, 1 = compressed)
    - 4 bytes: message length (big-endian)
    - N bytes: message data
    """
    flags = 1 if compressed else 0
    return struct.pack(">BI", flags, len(data)) + data


def decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a varint from bytes, return (value, new_position)."""
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
    """Decode a length-delimited string."""
    length, pos = decode_varint(data, pos)
    value = data[pos:pos + length].decode("utf-8")
    return value, pos + length


def decode_connect_envelope(data: bytes) -> list[bytes]:
    """Decode Connect protocol envelope(s) from response data.

    Returns list of message payloads.
    """
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

        # Check if it's a trailer (JSON)
        if flags & 0x02:
            # Trailer frame - usually JSON error or metadata
            continue

        messages.append(message)

    return messages


def parse_code_result(data: bytes, pos: int, end: int) -> dict:
    """Parse a CodeResult message."""
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
        else:
            # Skip unknown field
            pos = skip_field(data, pos, wire_type)

    return result


def parse_code_block(data: bytes, pos: int, end: int) -> dict:
    """Parse a CodeBlock message."""
    result = {
        "relativeWorkspacePath": "",
        "contents": "",
        "range": {"startPosition": {}, "endPosition": {}},
    }

    while pos < end:
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7

        if field_number == 1 and wire_type == 2:  # relative_workspace_path
            result["relativeWorkspacePath"], pos = decode_string(data, pos)
        elif field_number == 2 and wire_type == 2:  # range
            length, pos = decode_varint(data, pos)
            range_end = pos + length
            result["range"] = parse_range(data, pos, range_end)
            pos = range_end
        elif field_number == 3 and wire_type == 2:  # contents
            result["contents"], pos = decode_string(data, pos)
        else:
            pos = skip_field(data, pos, wire_type)

    return result


def parse_range(data: bytes, pos: int, end: int) -> dict:
    """Parse a Range message."""
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
    """Parse a Position message."""
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
    """Skip an unknown field based on wire type."""
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
    """Parse a SearchRepositoryResponse or SemSearchResponse message.

    Returns list of code results.
    """
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

            # Check if this is a nested response (SemSearchResponse)
            # or a direct CodeResult
            # Try parsing as CodeResult first
            try:
                result = parse_code_result(data, pos, item_end)
                if result["codeBlock"].get("relativeWorkspacePath"):
                    results.append(result)
                else:
                    # Might be nested response, try parsing inner
                    inner_results = parse_search_response(data[pos:item_end])
                    results.extend(inner_results)
            except Exception:
                pass
            pos = item_end
        else:
            pos = skip_field(data, pos, wire_type)

    return results
