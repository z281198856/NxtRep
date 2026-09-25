import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:image_picker/image_picker.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/media/image_upload.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/presentation/custom_plan_page.dart';
import 'package:nxtrep/features/training/presentation/plan_controller.dart';

void main() {
  test(
    'failed image parse keeps transcribed text available for correction',
    () async {
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'error': {
                'code': 'TRAINING_IMAGE_PARSE_FAILED',
                'message': '第 1 行：动作库中找不到该动作',
                'details': {'line': 1, 'recognized_text': '周一：未知动作 3×8'},
              },
            }),
            422,
            headers: {'content-type': 'application/json; charset=utf-8'},
          ),
        ),
      );
      final controller = PlanController(
        TrainingRepository(api),
        imageUploader: (bytes) async => UploadedImage(
          assetId: 'asset-image-2',
          bytes: bytes,
          contentType: 'image/png',
        ),
      );
      try {
        final result = await controller.importPlanImage(
          Uint8List.fromList([1]),
        );
        expect(result, isNull);
        expect(controller.errorMessage, contains('动作库中找不到'));
        expect(controller.recognizedImportText, '周一：未知动作 3×8');
      } finally {
        controller.dispose();
        api.close();
      }
    },
  );

  testWidgets(
    'image import uploads selected bytes and previews the recognized plan',
    (tester) async {
      final png = base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
      );
      final recognized = '周一：哑铃地板卧推 3×8-12';
      String? requestedAssetId;
      ImageSource? chosenSource;
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: MockClient((request) async {
          expect(request.url.path, '/api/v1/training/plan-drafts:parse-image');
          requestedAssetId =
              (jsonDecode(request.body) as Map)['image_asset_id'] as String;
          return http.Response(
            jsonEncode({
              'id': 'draft-image-1',
              'name': '图片导入训练计划',
              'status': 'editing',
              'version': 1,
              'weekly_frequency': 1,
              'recognized_text': recognized,
              'days': [
                {
                  'day_index': 1,
                  'name': '周一训练',
                  'estimated_minutes': 20,
                  'exercises': [
                    {
                      'exercise_id': 'exercise-1',
                      'exercise_name': '哑铃地板卧推',
                      'target_sets': 3,
                      'rep_min': 8,
                      'rep_max': 12,
                    },
                  ],
                },
              ],
            }),
            201,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      final controller = PlanController(
        TrainingRepository(api),
        imageUploader: (bytes) async {
          expect(bytes, png);
          return UploadedImage(
            assetId: 'asset-image-1',
            bytes: bytes,
            contentType: 'image/png',
          );
        },
      );
      addTearDown(() {
        controller.dispose();
        api.close();
      });
      await tester.pumpWidget(
        MaterialApp(
          home: CustomPlanPage(
            controller: controller,
            pickImage: (source) async {
              chosenSource = source;
              return Uint8List.fromList(png);
            },
          ),
        ),
      );
      await tester.tap(find.text('图片导入'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('选择训练表图片'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('从相册选择'));
      await tester.pumpAndSettle();
      expect(chosenSource, ImageSource.gallery);
      expect(find.byType(Image), findsOneWidget);

      await tester.ensureVisible(find.text('识别图片并预览'));
      await tester.tap(find.text('识别图片并预览'));
      await tester.pumpAndSettle();
      expect(requestedAssetId, 'asset-image-1');
      await tester.scrollUntilVisible(
        find.text('编辑识别结果'),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text(recognized), findsOneWidget);
      await tester.scrollUntilVisible(
        find.text('校验并启用计划'),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('校验并启用计划'), findsOneWidget);

      await tester.scrollUntilVisible(
        find.text('编辑识别结果'),
        -300,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('编辑识别结果'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextField>(find.widgetWithText(TextField, '粘贴训练安排'))
            .controller!
            .text,
        recognized,
      );
    },
  );
}
