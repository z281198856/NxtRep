import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/progress/data/body_progress_repository.dart';
import 'package:nxtrep/features/progress/domain/body_progress_models.dart';

void main() {
  http.Response jsonResponse(Object body, int status) => http.Response(
    jsonEncode(body),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );

  BodyProgressRepository repositoryWith(MockClient client) =>
      BodyProgressRepository(
        ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => 'access',
          httpClient: client,
        ),
      );

  test(
    'creates and lists body progress photos using the mobile contract',
    () async {
      late Map<String, dynamic> createBody;
      final photoJson = {
        'id': '00000000-0000-0000-0000-000000000101',
        'image_asset_id': '00000000-0000-0000-0000-000000000102',
        'captured_at': '2026-09-20T04:00:00Z',
        'view': 'front',
        'notes': '晨起自然站立',
        'assessment': null,
        'version': 1,
        'created_at': '2026-09-20T04:01:00Z',
      };
      final client = MockClient((request) async {
        if (request.method == 'POST') {
          createBody = jsonDecode(request.body) as Map<String, dynamic>;
          return jsonResponse(photoJson, 201);
        }
        return jsonResponse([photoJson], 200);
      });
      final repository = repositoryWith(client);

      final created = await repository.createPhoto(
        imageAssetId: photoJson['image_asset_id']! as String,
        capturedAt: DateTime.utc(2026, 9, 20, 4),
        view: BodyPhotoView.front,
        notes: '晨起自然站立',
      );
      final listed = await repository.listPhotos();

      expect(createBody['view'], 'front');
      expect(createBody['captured_at'], '2026-09-20T04:00:00.000Z');
      expect(created.view, BodyPhotoView.front);
      expect(listed.single.notes, '晨起自然站立');
    },
  );

  test('loads signed image access and parses an AI assessment', () async {
    final client = MockClient((request) async {
      if (request.url.path.endsWith('/download-intent')) {
        return jsonResponse({
          'method': 'GET',
          'download_url': 'https://oss.example.test/private-photo',
          'headers': {'x-oss-test': 'signed'},
          'expires_at': '2026-09-20T05:00:00Z',
        }, 200);
      }
      return jsonResponse({
        'photo_quality': [
          {
            'view': 'front',
            'lighting': 'good',
            'framing': 'good',
            'usable_for_assessment': true,
            'limitations': <String>[],
          },
        ],
        'summary': '肩部整体平衡。',
        'observations': [
          {
            'category': 'shoulder_balance',
            'observation': '左右肩高度接近',
            'visual_evidence': '正面照片中肩线接近水平',
            'confidence': 'medium',
          },
        ],
        'training_considerations': ['保持双侧训练量一致'],
        'recommended_next_steps': ['四周后同角度复拍'],
        'follow_up_questions': <String>[],
        'professional_review_recommended': false,
        'disclaimer': '仅基于照片中的可观察信息，不构成医学诊断或精确身体成分测量',
      }, 200);
    });
    final repository = repositoryWith(client);

    final download = await repository.getDownloadIntent('asset-id');
    final assessment = await repository.analyze('photo-id');

    expect(download.url, 'https://oss.example.test/private-photo');
    expect(download.headers['x-oss-test'], 'signed');
    expect(assessment.summary, '肩部整体平衡。');
    expect(assessment.observations.single.confidence, 'medium');
  });

  test('generates and parses a 30 day phase report', () async {
    late Map<String, dynamic> body;
    final client = MockClient((request) async {
      body = jsonDecode(request.body) as Map<String, dynamic>;
      return jsonResponse({
        'id': '00000000-0000-0000-0000-000000000111',
        'report_type': 'phase',
        'period_start': body['period_start'],
        'period_end': body['period_end'],
        'facts': {
          'training': {'workout_count': 3},
          'nutrition': {'record_completeness': '0.50'},
          'body': {'smoothed_change_kg': '-0.6'},
        },
        'missing_data': ['nutrition'],
        'recommendations': ['提高饮食记录完整度'],
        'evidence': <Object>[],
        'version': 1,
        'created_at': '2026-09-20T04:00:00Z',
      }, 200);
    });
    final repository = repositoryWith(client);

    final report = await repository.generatePhaseReport(days: 30);

    expect(body['period_start'], isNot(body['period_end']));
    expect(report.training['workout_count'], 3);
    expect(report.missingData, ['nutrition']);
  });
}
