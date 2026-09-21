import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/media/image_upload.dart';
import 'package:nxtrep/core/network/api_client.dart';

void main() {
  test('client limits can tighten but never enlarge server upload limits', () {
    const capabilities = ImageUploadCapabilities(
      acceptedContentTypes: ['image/jpeg'],
      convertBeforeUpload: ['image/heic'],
      maxBytes: 10 * 1024 * 1024,
      maxPixels: 25000000,
      maxDimension: 8192,
    );

    final constrained = capabilities.constrained(
      maxBytes: 1536 * 1024,
      maxPixels: 1440 * 1440,
      maxDimension: 1440,
    );

    expect(constrained.maxBytes, 1536 * 1024);
    expect(constrained.maxPixels, 1440 * 1440);
    expect(constrained.maxDimension, 1440);
    expect(constrained.acceptedContentTypes, ['image/jpeg']);
  });

  test('detects supported image formats from their bytes', () {
    expect(
      MobileImagePreparer.detectContentType(
        Uint8List.fromList([0xff, 0xd8, 0xff]),
      ),
      'image/jpeg',
    );
    expect(
      MobileImagePreparer.detectContentType(
        Uint8List.fromList([
          0x52,
          0x49,
          0x46,
          0x46,
          0,
          0,
          0,
          0,
          0x57,
          0x45,
          0x42,
          0x50,
        ]),
      ),
      'image/webp',
    );
  });

  testWidgets('uploads prepared bytes and completes the image asset', (
    tester,
  ) async {
    final png = base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    );
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      if (request.method == 'GET' &&
          request.url.path == '/api/v1/media/images/capabilities') {
        return http.Response(
          jsonEncode({
            'accepted_content_types': ['image/jpeg', 'image/png', 'image/webp'],
            'preferred_content_type': 'image/jpeg',
            'convert_before_upload': ['image/heic', 'image/heif'],
            'max_bytes': 1000000,
            'max_pixels': 100,
            'max_dimension': 100,
            'direct_upload_method': 'PUT',
            'upload_url_expires_in': 600,
          }),
          200,
        );
      }
      if (request.method == 'POST' &&
          request.url.path == '/api/v1/media/images/upload-intents') {
        expect(jsonDecode(request.body), {
          'purpose': 'chat_attachment',
          'content_type': 'image/png',
          'content_length': png.length,
        });
        return http.Response(
          jsonEncode({
            'asset_id': '00000000-0000-0000-0000-000000000041',
            'method': 'PUT',
            'upload_url': 'https://oss.example.test/signed-upload',
            'headers': {'x-oss-token': 'signed'},
            'expires_at': '2026-09-14T12:00:00Z',
            'status': 'pending_upload',
          }),
          201,
        );
      }
      if (request.method == 'PUT' && request.url.host == 'oss.example.test') {
        expect(request.headers['authorization'], isNull);
        expect(request.headers['x-oss-token'], 'signed');
        expect(request.headers['content-type'], 'image/png');
        expect(request.bodyBytes, png);
        return http.Response('', 200);
      }
      if (request.method == 'POST' && request.url.path.endsWith('/complete')) {
        expect(jsonDecode(request.body), {
          'expected_content_type': 'image/png',
          'expected_content_length': png.length,
        });
        return http.Response(
          jsonEncode({
            'id': '00000000-0000-0000-0000-000000000041',
            'purpose': 'chat_attachment',
            'content_type': 'image/png',
            'content_length': png.length,
            'status': 'ready',
            'created_at': '2026-09-14T11:00:00Z',
            'completed_at': '2026-09-14T11:00:01Z',
            'failure_reason': null,
          }),
          200,
        );
      }
      throw StateError('Unexpected request ${request.method} ${request.url}');
    });
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: client,
    );
    final repository = ImageUploadRepository(api, uploadClient: client);
    addTearDown(api.close);

    final uploaded = await tester.runAsync(
      () => repository.uploadChatImage(png),
    );

    expect(uploaded?.assetId, '00000000-0000-0000-0000-000000000041');
    expect(uploaded?.contentType, 'image/png');
    expect(requests.map((request) => request.method), [
      'GET',
      'POST',
      'PUT',
      'POST',
    ]);
  });
}
