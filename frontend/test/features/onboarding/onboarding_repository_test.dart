import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';
import 'package:nxtrep/features/onboarding/domain/onboarding_models.dart';

void main() {
  test('submits exactly the four-question onboarding contract', () async {
    Map<String, dynamic>? goalsBody;
    Map<String, dynamic>? profileBody;
    final httpClient = MockClient((request) async {
      switch ('${request.method} ${request.url.path}') {
        case 'GET /api/v1/profile':
          return http.Response(
            jsonEncode({
              'experience_level': null,
              'weekly_training_days': null,
              'version': 3,
            }),
            200,
          );
        case 'GET /api/v1/profile/goals-and-constraints':
          return http.Response(
            jsonEncode({
              'error': {
                'code': 'GOALS_NOT_FOUND',
                'message': 'Goals and constraints not found',
              },
            }),
            404,
          );
        case 'PUT /api/v1/profile/goals-and-constraints':
          goalsBody = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response('{}', 200);
        case 'PATCH /api/v1/profile':
          profileBody = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response('{}', 200);
        default:
          throw StateError(
            'Unexpected request: ${request.method} ${request.url}',
          );
      }
    });
    final client = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access-token',
      httpClient: httpClient,
    );

    await OnboardingRepository(client).complete(
      OnboardingSubmission(
        goalType: 'strength',
        weeklyTrainingDays: 4,
        equipment: TrainingMode.gymEquipment.equipmentCodes,
      ),
    );

    expect(goalsBody?['goal_type'], 'strength');
    expect(goalsBody?['equipment'], ['barbell', 'dumbbell', 'cable', 'rack']);
    expect(goalsBody?['pain_or_injuries'], isEmpty);
    expect(goalsBody?.containsKey('expected_version'), isFalse);
    expect(profileBody, {
      'weekly_training_days': 4,
      'experience_level': 'beginner',
      'expected_version': 3,
    });
  });

  test('keeps legacy concrete equipment submissions compatible', () async {
    Map<String, dynamic>? goalsBody;
    final httpClient = MockClient((request) async {
      switch ('${request.method} ${request.url.path}') {
        case 'GET /api/v1/profile':
          return http.Response(
            jsonEncode({
              'experience_level': 'intermediate',
              'weekly_training_days': 5,
              'version': 8,
            }),
            200,
          );
        case 'GET /api/v1/profile/goals-and-constraints':
          return http.Response(jsonEncode({'version': 6}), 200);
        case 'PUT /api/v1/profile/goals-and-constraints':
          goalsBody = jsonDecode(request.body) as Map<String, dynamic>;
          return http.Response('{}', 200);
        case 'PATCH /api/v1/profile':
          return http.Response('{}', 200);
        default:
          throw StateError(
            'Unexpected request: ${request.method} ${request.url}',
          );
      }
    });
    final client = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access-token',
      httpClient: httpClient,
    );

    await OnboardingRepository(client).complete(
      const OnboardingSubmission(
        goalType: 'maintain',
        weeklyTrainingDays: 5,
        equipment: ['kettlebell', 'machine'],
      ),
    );

    expect(goalsBody?['equipment'], ['kettlebell', 'machine']);
    expect(goalsBody?['expected_version'], 6);
  });
}
