"""Search, inspect and stage web images for phone-owned chat history."""
from .Prompts import AUTONOMOUS_WEB_IMAGES_TEXT

from .Prompts import media_handling
import base64
import hashlib
import json
import sqlite3

from .harness_runtime import HarnessToolValidationError
from .web_image_download import PublicImageDownloader, ImageDownloadError
from .web_image_style import image_style, apply_style


def recent_web_image_source_urls(db_path, conversation_id, *, limit=24):
    """Return web-image sources already sent in this conversation.

    The web-image tool is recreated for each Agent turn, so its in-memory
    candidates cannot prevent a later turn from selecting the same source.
    Attachments are the delivery record that survives between turns.
    """
    if not db_path or not conversation_id:
        return set()
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT metadata_json FROM message_attachments "
                "WHERE conversation_id=? ORDER BY rowid DESC LIMIT ?",
                (str(conversation_id), int(limit)),
            ).fetchall()
    except sqlite3.Error:
        return set()
    sources = set()
    for (raw_metadata,) in rows:
        try:
            metadata = json.loads(raw_metadata or '{}')
        except (TypeError, json.JSONDecodeError):
            continue
        if metadata.get('source') != 'web_search':
            continue
        source_url = str(metadata.get('source_url') or '').strip()
        if source_url:
            sources.add(source_url)
    return sources


class WebImageTools:
    def __init__(self, search, *, username, downloader=None, transfer_store=None, transfer_discard=None,
                 excluded_source_urls=()):
        self.search_provider = search
        self.username = username
        self.downloader = downloader or PublicImageDownloader()
        self.transfer_store = transfer_store
        self.transfer_discard = transfer_discard
        self.transfers = {}
        self.excluded_source_urls = {str(url).strip() for url in excluded_source_urls if url and str(url).strip()}
        self.candidates, self.downloaded, self.selected = {}, {}, {}
        self.purposes = {}
        self.download_calls = 0
        self.require_exact_match = False

    async def search(self, arguments):
        if arguments.get('subject_type') not in {'pony', 'other', 'mixed'}:
            raise HarnessToolValidationError(AUTONOMOUS_WEB_IMAGES_TEXT['subject_type_1'])
        result = await self.search_provider.search_images(apply_style(arguments))
        candidates = []
        excluded_count = 0
        for row in result['results']:
            if str(row.get('source_url') or '').strip() in self.excluded_source_urls:
                excluded_count += 1
                continue
            ref = 'web:' + hashlib.sha256(row['image_url'].encode()).hexdigest()[:20]
            self.candidates[ref] = row
            candidates.append({**row, 'image_ref': ref})
        duplicate_note = (AUTONOMOUS_WEB_IMAGES_TEXT['duplicate_note_1'] % excluded_count
                          if excluded_count else '')
        return {**result, 'results': candidates,
                'note': AUTONOMOUS_WEB_IMAGES_TEXT['search_1'] + duplicate_note + media_handling}

    def candidate(self, arguments):
        ref = arguments.get('image_ref')
        if ref not in self.candidates:
            raise HarnessToolValidationError(AUTONOMOUS_WEB_IMAGES_TEXT['candidate_1'])
        return ref, self.candidates[ref]

    async def read(self, arguments):
        ref, candidate = self.candidate(arguments)
        if ref not in self.downloaded:
            self.download_calls += 1
            try:
                self.downloaded[ref] = await self.downloader.download(candidate['image_url'])
            except ImageDownloadError as exc:
                return {'status': 'unavailable', 'reason': str(exc),
                        'note': AUTONOMOUS_WEB_IMAGES_TEXT['read_1']}
        item = self.downloaded[ref]
        return {'content': [
            {'type': 'text', 'text': json.dumps({'status': 'downloaded', 'image_ref': ref,
                'source_url': candidate['source_url'], 'title': candidate['title'],
                'width': item['width'], 'height': item['height'],
                'animated': item.get('animated', False), 'preview_only': item.get('animated', False),
                'note': AUTONOMOUS_WEB_IMAGES_TEXT['read_2'] + image_style + media_handling}, ensure_ascii=False)},
            {'type': 'image', 'mimeType': item.get('preview_mime_type', item['mime_type']),
             'data': base64.b64encode(item.get('preview_data', item['data'])).decode('ascii')}]}

    def delivery_context(self):
        """Carry inspected pixels across the exploration/finalization model boundary."""
        blocks = []
        for ref, item in self.downloaded.items():
            blocks.extend([
                {'type': 'text', 'text': AUTONOMOUS_WEB_IMAGES_TEXT['delivery_context_1'] + ref},
                {'type': 'image', 'mimeType': item.get('preview_mime_type', item['mime_type']),
                 'data': base64.b64encode(item.get('preview_data', item['data'])).decode('ascii')}])
        return blocks

    async def stage(self, arguments):
        ref, _ = self.candidate(arguments)
        match_kind = arguments.get('match_kind', 'exact')
        if match_kind not in {'exact', 'approximate'}:
            raise HarnessToolValidationError(AUTONOMOUS_WEB_IMAGES_TEXT['stage_2'])
        if self.require_exact_match and match_kind == 'approximate':
            raise HarnessToolValidationError(AUTONOMOUS_WEB_IMAGES_TEXT['stage_3'])
        if ref not in self.downloaded:
            raise HarnessToolValidationError(AUTONOMOUS_WEB_IMAGES_TEXT['stage_4'])
        position = arguments.get('after_bubble_index', 1)
        if type(position) is not int or not 0 <= position <= 6:
            raise HarnessToolValidationError(AUTONOMOUS_WEB_IMAGES_TEXT['stage_5'])
        purpose = arguments.get('purpose', 'image')
        if purpose not in {'image', 'sticker'}:
            raise HarnessToolValidationError('purpose must be image or sticker')
        if self.transfer_store is None:
            from ..chat_image_transfer import store_web_image_transfer, discard_web_image_transfer
            self.transfer_store, self.transfer_discard = store_web_image_transfer, discard_web_image_transfer
        if ref not in self.transfers:
            item = self.downloaded[ref]
            try:
                self.transfers[ref] = self.transfer_store(item['data'], item['mime_type'], self.username)
            except ValueError:
                return {'staged': False, 'reason': 'transfer_unavailable',
                        'note': AUTONOMOUS_WEB_IMAGES_TEXT['stage_6']}
        self.selected[ref] = position
        self.purposes[ref] = purpose
        return {'staged': True, 'image_ref': ref,
                'purpose': purpose,
                'animated': self.downloaded[ref].get('animated', False),
                'note': AUTONOMOUS_WEB_IMAGES_TEXT['stage_1']}

    def register(self, capability):
        from .derpibooru_images import RATINGS
        capability('search_images', AUTONOMOUS_WEB_IMAGES_TEXT['register_3'] + image_style + media_handling, {
            'type': 'object', 'properties': {'query': {'type': 'string', 'minLength': 1, 'maxLength': 300},
                'subject_type': {'type': 'string', 'enum': ['pony', 'other', 'mixed'],
                    'description': AUTONOMOUS_WEB_IMAGES_TEXT['subject_type_2']},
                'derpibooru_tags': {'type': 'string', 'minLength': 1, 'maxLength': 300},
                'animated': {'type': 'boolean', 'description': AUTONOMOUS_WEB_IMAGES_TEXT['animated_search']},
                'style': {'type': 'string', 'enum': ['g4_pony', 'user_requested'],
                          'description': AUTONOMOUS_WEB_IMAGES_TEXT['register_4']},
                'rating': {'type': 'string', 'enum': list(RATINGS)}},
            'required': ['query', 'subject_type'], 'additionalProperties': False}, self.search)
        schema = {'type': 'object', 'properties': {'image_ref': {'type': 'string', 'maxLength': 64}},
                  'required': ['image_ref'], 'additionalProperties': False}
        capability('read_web_image', AUTONOMOUS_WEB_IMAGES_TEXT['register_1'], schema, self.read)
        capability('stage_web_image', AUTONOMOUS_WEB_IMAGES_TEXT['register_2'], {
            **schema, 'properties': {**schema['properties'],
                'match_kind': {'type': 'string', 'enum': ['exact', 'approximate']},
                'purpose': {'type': 'string', 'enum': ['image', 'sticker'],
                            'description': AUTONOMOUS_WEB_IMAGES_TEXT['sticker_purpose']},
                'after_bubble_index': {'type': 'integer', 'minimum': 0, 'maximum': 6}},
                'required': ['image_ref', 'match_kind']}, self.stage)

    def apply_to_request(self, request, bubble_count):
        from .autonomous_stickers import apply_image_attachments
        items = []
        for ref, position in self.selected.items():
            item, candidate = self.downloaded[ref], self.candidates[ref]
            url = self.transfers[ref]
            rid = 'agent_web_image_' + ref[4:]
            attachment = {'id': rid, 'type': 'image', 'url': url, 'name': candidate['title'],
                'width': item['width'], 'height': item['height'],
                'mime_type': item['mime_type'], 'is_animated': item.get('animated', False),
                'metadata': {'source': 'web_search', 'request_id': rid, 'source_url': candidate['source_url'],
                             'purpose': self.purposes.get(ref, 'image'),
                             'sha256': hashlib.sha256(item['data']).hexdigest(), 'ephemeral': True}}
            items.append((attachment, min(position, bubble_count)))
        apply_image_attachments(request, items, bubble_count, append=True)
        self.transfers.clear()  # Ownership passes to phone receipt / TTL cleanup.
        self.discard()

    def discard(self):
        if self.transfer_discard:
            for url in self.transfers.values():
                self.transfer_discard(url.rsplit('/', 1)[-1], self.username)
        self.transfers.clear()
        self.downloaded.clear()
        self.selected.clear()
        self.purposes.clear()
