import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/profile/data/profile_repository.dart';
import 'package:nxtrep/features/profile/domain/profile_models.dart';

void main() {
  test('loads profile, training preferences and settings', () async {
    final client = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.test/api/v1')),
      accessTokenProvider: () => 'token',
      httpClient: MockClient((request) async {
        return switch (request.url.path) {
          '/api/v1/profile' => _json(_profileJson()),
          '/api/v1/profile/goals-and-constraints' => _json(_preferencesJson()),
          '/api/v1/settings' => _json(_settingsJson()),
          _ => http.Response('not found', 404),
        };
      }),
    );
    addTearDown(client.close);
    final repository = ProfileRepository(client);

    final profile = await repository.getProfile();
    final preferences = await repository.getTrainingPreferences();
    final settings = await repository.getSettings();

    expect(profile.displayName, '小齐');
    expect(profile.heightCm, 178.5);
    expect(preferences.goalType, 'muscle_gain');
    expect(preferences.trainingMode, ProfileTrainingMode.bodyweight);
    expect(settings.privacyMode, 'private');
  });

  test(
    'updates training preferences with versions and preserved constraints',
    () async {
      final requests = <http.Request>[];
      final client = ApiClient(
        config: ApiConfig(baseUri: Uri.parse('https://api.test/api/v1')),
        accessTokenProvider: () => 'token',
        httpClient: MockClient((request) async {
          requests.add(request);
          return switch ((request.method, request.url.path)) {
            ('POST', '/api/v1/profile/goal-check') => _json({
              'valid': true,
              'warnings': <String>[],
            }),
            ('PUT', '/api/v1/profile/goals-and-constraints') => _json(
              _preferencesJson(
                version: 5,
                equipment: const ['barbell', 'dumbbell', 'cable', 'rack'],
              ),
            ),
            ('PATCH', '/api/v1/profile') => _json(
              _profileJson(version: 4, weeklyTrainingDays: 4),
            ),
            _ => http.Response('not found', 404),
          };
        }),
      );
      addTearDown(client.close);
      final repository = ProfileRepository(client);

      final result = await repository.updateTrainingPreferences(
        UserProfile.fromJson(_profileJson()),
        TrainingPreferences.fromJson(_preferencesJson()),
        const TrainingPreferencesInput(
          goalType: 'strength',
          weeklyTrainingDays: 4,
          trainingMode: ProfileTrainingMode.gymEquipment,
        ),
      );

      expect(result.profile.weeklyTrainingDays, 4);
      expect(result.preferences.trainingMode, ProfileTrainingMode.gymEquipment);
      final goalBody = jsonDecode(requests[0].body) as Map<String, dynamic>;
      expect(goalBody['goal_type'], 'strength');
      expect(goalBody['expected_version'], 4);
      expect(goalBody['equipment'], ['barbell', 'dumbbell', 'cable', 'rack']);
      expect(
        (goalBody['pain_or_injuries'] as List<dynamic>).single,
        containsPair('body_part', '右膝'),
      );
      final profileBody = jsonDecode(requests[2].body) as Map<String, dynamic>;
      expect(profileBody['weekly_training_days'], 4);
      expect(profileBody['expected_version'], 3);
    },
  );
}

http.Response _json(Object value) => http.Response(
  jsonEncode(value),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

Map<String, Object?> _profileJson({
  int version = 3,
  int weeklyTrainingDays = 3,
}) => {
  'display_name': '小齐',
  'sex': 'male',
  'birth_date': '2000-01-02',
  'height_cm': '178.5',
  'experience_level': 'beginner',
  'weekly_training_days': weeklyTrainingDays,
  'session_duration_minutes': 60,
  'timezone': 'Asia/Shanghai',
  'version': version,
};

Map<String, Object?> _preferencesJson({
  int version = 4,
  List<String> equipment = const ['bodyweight'],
}) => {
  'version': version,
  'goal': {
    'id': '00000000-0000-0000-0000-000000000001',
    'goal_type': 'muscle_gain',
    'target_date': null,
    'target_weight_kg': null,
    'status': 'active',
  },
  'constraints': {
    'equipment': equipment,
    'preferred_exercises': <String>[],
    'disliked_exercises': <String>[],
    'pain_or_injuries': [
      {
        'kind': 'current_pain',
        'body_part': '右膝',
        'severity': null,
        'notes': null,
      },
    ],
    'allergies': <String>[],
    'dietary_preferences': <String>[],
  },
  'warnings': <String>[],
};

Map<String, Object?> _settingsJson() => {
  'unit_system': 'metric',
  'timezone': 'Asia/Shanghai',
  'privacy_mode': 'private',
  'share_anonymous_analytics': false,
  'version': 2,
};
