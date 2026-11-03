import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/media/image_upload.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/nutrition/data/nutrition_repository.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_controller.dart';

void main() {
  test('photo failure retains upload, retries latest notes, and new photo uploads separately', () async {
    var uploads = 0;
    final requests = <Map<String, dynamic>>[];
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://test/api/v1')),
      accessTokenProvider: () => 'test',
      httpClient: MockClient((request) async {
        requests.add(jsonDecode(request.body) as Map<String, dynamic>);
        return http.Response(
          jsonEncode({
            'error': {'code': 'VISION_MODEL_BUSY', 'message': 'busy'},
          }),
          503,
        );
      }),
    );
    final controller = NutritionController(
      NutritionRepository(api),
      imageUploader: (bytes) async {
        uploads++;
        return UploadedImage(
          assetId: 'image-$uploads',
          bytes: bytes,
          contentType: 'image/png',
        );
      },
    );
    addTearDown(controller.dispose);
    addTearDown(api.close);
    final bytes = Uint8List.fromList([1, 2, 3]);
    await controller.estimatePhoto(
      bytes: bytes,
      mealType: 'lunch',
      notes: '一碗',
    );
    expect(controller.errorMessage, contains('已保留'));
    expect(controller.submitting, isFalse);
    await controller.estimatePhoto(
      bytes: bytes,
      mealType: 'dinner',
      notes: '半碗',
    );
    expect(uploads, 1);
    expect(requests.last['image_asset_id'], 'image-1');
    expect(requests.last['meal_type'], 'dinner');
    expect(requests.last['notes'], '半碗');
    await controller.estimatePhoto(
      bytes: Uint8List.fromList([4]),
      mealType: 'lunch',
    );
    expect(uploads, 2);
    expect(requests.last['image_asset_id'], 'image-2');
  });

  test('logout during upload does not start a recognition or notify a disposed controller', () async {
    final upload = Completer<UploadedImage>();
    var requests = 0;
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://test/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async {
        requests++;
        return http.Response('{}', 200);
      }),
    );
    addTearDown(api.close);
    final controller = NutritionController(
      NutritionRepository(api),
      imageUploader: (_) => upload.future,
    );
    final bytes = Uint8List.fromList([1]);
    final pending = controller.estimatePhoto(bytes: bytes, mealType: 'lunch');
    expect(controller.photoActivity, contains('上传'));
    controller.dispose();
    upload.complete(
      UploadedImage(assetId: 'image', bytes: bytes, contentType: 'image/png'),
    );
    expect(await pending, isNull);
    expect(requests, 0);
  });

  test(
    'malformed photo response releases busy state and remains retryable',
    () async {
      final api = ApiClient(
        config: ApiConfig(baseUri: Uri.parse('https://test/api/v1')),
        accessTokenProvider: () => 'test',
        httpClient: MockClient((_) async => http.Response('{}', 200)),
      );
      final controller = NutritionController(
        NutritionRepository(api),
        imageUploader: (bytes) async => UploadedImage(
          assetId: 'image',
          bytes: bytes,
          contentType: 'image/png',
        ),
      );
      addTearDown(controller.dispose);
      addTearDown(api.close);
      expect(
        await controller.estimatePhoto(
          bytes: Uint8List.fromList([1]),
          mealType: 'lunch',
        ),
        isNull,
      );
      expect(controller.submitting, isFalse);
      expect(controller.errorMessage, contains('已保留'));
    },
  );
}
