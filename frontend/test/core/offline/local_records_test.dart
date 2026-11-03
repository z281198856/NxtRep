import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';
import 'package:nxtrep/core/offline/form_draft.dart';
import 'package:nxtrep/core/offline/local_records.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';
import 'package:nxtrep/features/nutrition/data/nutrition_repository.dart';
import 'package:nxtrep/features/nutrition/domain/nutrition_models.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_controller.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_photo_page.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';

class MemoryLocalStore implements LocalDataStore {
  final values = <String, String>{};
  bool failWrite = false;
  @override
  Future<String?> read(String key) async => values[key];
  @override
  Future<void> write(String key, String value) async {
    if (failWrite) throw StateError('disk unavailable');
    values[key] = value;
  }

  @override
  Future<void> delete(String key) async => values.remove(key);
}

class _Tokens implements RefreshTokenStore {
  String? value = 'refresh';
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String token) async => value = token;
  @override
  Future<void> delete() async => value = null;
}

class _UnreadableTokens extends _Tokens {
  @override
  Future<String?> read() async =>
      throw StateError('platform store unavailable');
}

const _network = ApiException(code: 'NETWORK_ERROR', message: 'offline');
final _saved = throwsA(
  isA<ApiException>().having((e) => e.code, 'code', 'RECORD_SAVED_LOCALLY'),
);
final _water = {'amount_ml': 250, 'consumed_at': '2026-11-02T01:00:00Z'};
Future<Object?> _unavailable(
  String path,
  Map<String, dynamic> body,
  String key,
) async => throw _network;

void main() {
  test('unreadable login storage leaves the loading screen without deleting drafts', () async {
    final store = MemoryLocalStore();
    final local = LocalRecords(store);
    await local.bind('server', 'alice');
    await local.saveDraft('input', '草稿', {'text': '保留输入'});
    final api = ApiClient(
      config: ApiConfig(),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw _network),
    )..localRecords = local;
    final session = SessionController(
      authRepository: AuthRepository(
        apiClient: api,
        tokens: SessionTokens(_UnreadableTokens()),
      ),
      onboardingRepository: OnboardingRepository(api),
    );
    addTearDown(api.close);
    addTearDown(session.dispose);
    await session.initialize();
    expect(session.phase, SessionPhase.signedOut);
    expect(session.errorMessage, contains('本机登录状态'));
    expect((await local.readDraft('input'))!['text'], '保留输入');
  });

  test('switching accounts during HTTP preserves original queue and stops following sends', () async {
    final local = LocalRecords(MemoryLocalStore());
    await local.bind('server', 'alice');
    local.localOnly = true;
    for (final key in ['one', 'two']) {
      await expectLater(
        local.record('/nutrition/water', _water, key, _unavailable),
        _saved,
      );
    }
    local.localOnly = false;
    final started = Completer<void>(), reply = Completer<Object?>();
    var sent = 0;
    final syncing = local.sync((p, b, k) {
      sent++;
      started.complete();
      return reply.future;
    });
    await started.future;
    await local.bind('server', 'bob');
    reply.complete({});
    await syncing;
    expect(sent, 1);
    expect(local.pending, isEmpty);
    await local.bind('server', 'alice');
    expect(local.pending.length, 2);
  });

  test(
    'ended workout clears the old active cache before going offline',
    () async {
      final local = LocalRecords(MemoryLocalStore());
      await local.bind('server', 'alice');
      await local.cache('/workouts/active', null, {'id': 'old'});
      final api = ApiClient(
        config: ApiConfig(),
        accessTokenProvider: () => 'token',
        httpClient: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'error': {'code': 'WORKOUT_NOT_FOUND', 'message': 'ended'},
            }),
            404,
          ),
        ),
      )..localRecords = local;
      addTearDown(api.close);
      final repository = TrainingRepository(api);
      expect(await repository.getActiveWorkout(), isNull);
      local.localOnly = true;
      expect(await repository.getActiveWorkout(), isNull);
    },
  );

  test('incomplete success response never drops a queued record', () async {
    final local = LocalRecords(MemoryLocalStore());
    await local.bind('server', 'alice');
    final api = ApiClient(
      config: ApiConfig(),
      accessTokenProvider: () => 'token',
      httpClient: MockClient((_) async => http.Response('{}', 201)),
    )..localRecords = local;
    addTearDown(api.close);
    await expectLater(
      api.post('/nutrition/water', body: _water, idempotencyKey: 'stable'),
      _saved,
    );
    expect(local.pending.single.key, 'stable');
  });

  testWidgets(
    'photo draft restores bytes, estimate and user edits without a model call',
    (tester) async {
      final local = LocalRecords(MemoryLocalStore());
      await local.bind('server', 'alice');
      const totals = NutritionTotals(
        kcal: 195,
        proteinG: 3,
        carbsG: 42,
        fatG: 0.4,
      );
      const range = NutritionEstimateRange(
        minimum: totals,
        estimated: totals,
        maximum: totals,
      );
      final date = DateTime(2026, 10, 31);
      final estimate = NutritionPhotoDraft(
        imageAssetId: 'image',
        mealType: 'lunch',
        eatenAt: date,
        items: const [
          NutritionPhotoItem(
            name: '米饭',
            amountG: 150,
            amountMinG: 100,
            amountMaxG: 200,
            confidence: 'low',
            status: 'estimated',
            assumptions: [],
            questions: [],
            nutrition: range,
          ),
        ],
        totals: range,
        isComplete: true,
        assumptions: const [],
        questions: const [],
      );
      await local.saveDraft('photo:${date.toIso8601String()}', '照片', {
        'photo': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
        'notes': '实际只有半碗',
        'estimated_notes': '一碗',
        'meal': 'lunch',
        'result': estimate.toJson(),
        'editors': [
          {
            'name': '熟米饭（用户更正）',
            'amount': '120',
            'kcal': '156',
            'protein': '2.4',
            'carbs': '33.6',
            'fat': '0.3',
          },
        ],
      });
      var calls = 0;
      final api = ApiClient(
        config: ApiConfig(),
        accessTokenProvider: () => 'token',
        httpClient: MockClient((_) async {
          calls++;
          throw _network;
        }),
      );
      final controller = NutritionController(NutritionRepository(api));
      addTearDown(api.close);
      addTearDown(controller.dispose);
      await tester.pumpWidget(
        LocalRecordsScope(
          records: local,
          child: MaterialApp(
            home: NutritionPhotoPage(controller: controller, recordDate: date),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('实际只有半碗'), findsOneWidget);
      expect(find.byType(Image), findsOneWidget);
      await tester.scrollUntilVisible(
        find.text('熟米饭（用户更正）'),
        150,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('120'), findsOneWidget);
      expect(find.text('156'), findsOneWidget);
      expect(calls, 0);
      expect(local.pending, isEmpty);
      await tester.pumpWidget(const SizedBox());
    },
  );

  test(
    'uncertain committed write replays exact payload and key after restart',
    () async {
      final store = MemoryLocalStore();
      final sent = <String>[];
      final server = <String, Map<String, dynamic>>{};
      var loseReply = true;
      Future<Object?> send(
        String path,
        Map<String, dynamic> body,
        String key,
      ) async {
        sent.add(key);
        server.putIfAbsent(key, () => body);
        if (loseReply) throw _network;
        return {'id': 'server-water'};
      }

      final first = LocalRecords(store);
      await first.bind('server', 'alice');
      await expectLater(
        first.record('/nutrition/water', _water, 'stable-id', send),
        _saved,
      );
      expect(server.length, 1);
      final restarted = LocalRecords(store);
      await restarted.bind('server', 'alice');
      expect(restarted.pending.single.body, _water);
      loseReply = false;
      await restarted.sync(send);
      expect(sent, ['stable-id', 'stable-id']);
      expect(server.length, 1);
      expect(restarted.pending, isEmpty);
      final third = LocalRecords(store);
      await third.bind('server', 'alice');
      expect(third.pending, isEmpty);
    },
  );

  test(
    'never-attempted records can sync days later; uncertain old writes stop',
    () async {
      var now = DateTime.utc(2026, 11, 2);
      final local = LocalRecords(MemoryLocalStore(), now: () => now);
      await local.bind('server', 'alice');
      local.localOnly = true;
      await expectLater(
        local.record('/nutrition/water', _water, 'never-sent', _unavailable),
        _saved,
      );
      now = now.add(const Duration(days: 3));
      local.localOnly = false;
      var calls = 0;
      await local.sync((p, b, k) async {
        calls++;
        return {};
      });
      expect(calls, 1);
      await expectLater(
        local.record('/nutrition/water', _water, 'uncertain', _unavailable),
        _saved,
      );
      now = now.add(const Duration(hours: 23));
      await local.sync((p, b, k) async {
        calls++;
        return {};
      });
      expect(calls, 1);
      expect(local.pending.single.issue, contains('安全重试时限'));
    },
  );

  test(
    'account and server isolate pending records, drafts and caches',
    () async {
      final local = LocalRecords(MemoryLocalStore());
      await local.bind('server-a', 'alice');
      local.localOnly = true;
      await expectLater(
        local.record('/nutrition/water', _water, 'alice-only', _unavailable),
        _saved,
      );
      await local.saveDraft('input', '草稿', {'text': 'Alice'});
      await local.cache('/settings', null, {'unit_system': 'imperial'});
      await local.bind('server-a', 'bob');
      expect(local.pending, isEmpty);
      expect(await local.readDraft('input'), isNull);
      expect(
        () => local.cached('/settings', null),
        throwsA(isA<ApiException>()),
      );
      await local.bind('server-b', 'alice');
      expect(local.pending, isEmpty);
      await local.bind('server-a', 'alice');
      expect(local.pending.single.key, 'alice-only');
      expect((await local.readDraft('input'))!['text'], 'Alice');
    },
  );

  test('a slow HTTP sync does not block durable draft writes', () async {
    final local = LocalRecords(MemoryLocalStore());
    await local.bind('server', 'alice');
    final started = Completer<void>();
    final reply = Completer<Object?>();
    final recording = local.record('/nutrition/water', _water, 'slow', (
      p,
      b,
      k,
    ) {
      started.complete();
      return reply.future;
    });
    await started.future;
    await local
        .saveDraft('typing', '输入', {'text': '不会被网络阻塞'})
        .timeout(const Duration(seconds: 1));
    expect((await local.readDraft('typing'))!['text'], '不会被网络阻塞');
    reply.complete({});
    await recording;
  });

  test(
    'durable queue consumes form draft even if killed before UI cleanup',
    () async {
      final store = MemoryLocalStore();
      final local = LocalRecords(store);
      await local.bind('server', 'alice');
      await local.saveDraft('water-form', '饮水', {'amount': '250'});
      local.localOnly = true;
      await expectLater(
        local.record(
          '/nutrition/water',
          _water,
          'water',
          _unavailable,
          draftKey: 'water-form',
        ),
        _saved,
      );
      final restart = LocalRecords(store);
      await restart.bind('server', 'alice');
      expect(await restart.readDraft('water-form'), isNull);
      expect(restart.drafts, isEmpty);
      await restart.sync((p, b, k) async => {});
      expect(await restart.readDraft('water-form'), isNull);
    },
  );

  test('disk failure before write sends nothing and preserves draft', () async {
    final store = MemoryLocalStore();
    final local = LocalRecords(store);
    await local.bind('server', 'alice');
    await local.saveDraft('water', '饮水', {'amount': '250'});
    store.failWrite = true;
    var requests = 0;
    await expectLater(
      local.record('/nutrition/water', _water, 'id', (p, b, k) async {
        requests++;
        return {};
      }),
      throwsA(
        isA<ApiException>().having(
          (e) => e.code,
          'code',
          'LOCAL_STORAGE_FAILED',
        ),
      ),
    );
    expect(requests, 0);
    expect(local.pending, isEmpty);
    expect(await local.readDraft('water'), isNotNull);
  });

  test('corrupt journal is retained and never silently replaced', () async {
    final store = MemoryLocalStore();
    final key = 'records.${base64Url.encode(utf8.encode('server|alice'))}';
    store.values[key] = '{broken';
    final local = LocalRecords(store);
    await expectLater(local.bind('server', 'alice'), throwsFormatException);
    expect(local.bound, isFalse);
    expect(store.values[key], '{broken');
  });

  test(
    'workout conflict blocks later sets for that workout, not unrelated water',
    () async {
      final local = LocalRecords(MemoryLocalStore());
      await local.bind('server', 'alice');
      local.localOnly = true;
      for (var i = 1; i <= 2; i++) {
        await expectLater(
          local.record(
            '/workouts/abc/sets',
            {'set_index': i},
            'set-$i',
            _unavailable,
          ),
          _saved,
        );
      }
      await expectLater(
        local.record('/nutrition/water', _water, 'water', _unavailable),
        _saved,
      );
      local.localOnly = false;
      final sent = <String>[];
      await local.sync((p, b, k) async {
        sent.add(k);
        if (k.startsWith('set')) {
          throw const ApiException(
            statusCode: 409,
            code: 'CONFLICT',
            message: '训练已结束',
          );
        }
        return {};
      });
      expect(sent, ['set-1', 'water']);
      expect(local.pending.map((e) => e.key), ['set-1', 'set-2']);
      expect(local.needsAttention, isTrue);
    },
  );

  test(
    'pending set overlay restores index without duplicating acknowledged set',
    () async {
      final local = LocalRecords(MemoryLocalStore());
      await local.bind('server', 'alice');
      local.localOnly = true;
      final body = {
        'workout_exercise_id': 'exercise',
        'set_index': 2,
        'client_generated_id': 'set-2',
      };
      await expectLater(
        local.record('/workouts/abc/sets', body, 'set-2', _unavailable),
        _saved,
      );
      final workout = {
        'id': 'abc',
        'exercises': [
          {
            'id': 'exercise',
            'sets': [
              {'id': 'set-1', 'set_index': 1},
            ],
          },
        ],
      };
      final projected = local.project('/workouts/active', workout) as Map;
      expect(
        ((projected['exercises'] as List).single['sets'] as List).length,
        2,
      );
      final acknowledged = {
        'id': 'abc',
        'exercises': [
          {
            'id': 'exercise',
            'sets': [
              {'id': 'real-id', ...body},
            ],
          },
        ],
      };
      final merged = local.project('/workouts/active', acknowledged) as Map;
      expect(((merged['exercises'] as List).single['sets'] as List).length, 1);
    },
  );

  test(
    'authentication errors never fall back to cached personal data',
    () async {
      final local = LocalRecords(MemoryLocalStore());
      await local.bind('server', 'alice');
      await local.cache('/profile', null, {'display_name': 'Alice'});
      final api = ApiClient(
        config: ApiConfig(),
        accessTokenProvider: () => 'invalid',
        httpClient: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'error': {'code': 'INVALID_ACCESS_TOKEN', 'message': 'revoked'},
            }),
            401,
          ),
        ),
      )..localRecords = local;
      addTearDown(api.close);
      await expectLater(
        api.get('/profile'),
        throwsA(
          isA<ApiException>().having(
            (e) => e.code,
            'code',
            'INVALID_ACCESS_TOKEN',
          ),
        ),
      );
      expect(local.usingCache, isFalse);
      expect(LocalRecords.canRecord('POST', '/agent/chat', 'id'), isFalse);
      expect(
        LocalRecords.canRecord('POST', '/confirmations/id/approve', 'id'),
        isFalse,
      );
    },
  );

  test('restart offline opens only a previously verified account with retained login token', () async {
    final local = LocalRecords(MemoryLocalStore());
    final config = ApiConfig();
    await local.saveBootstrap({
      'server': config.resolve('/').toString(),
      'account': {
        'id': 'alice',
        'username': 'Alice',
        'status': 'active',
        'is_admin': false,
        'profile_initialized': true,
        'password_setup_required': false,
      },
    });
    final tokenStore = _Tokens();
    final api = ApiClient(
      config: config,
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw _network),
    )..localRecords = local;
    final auth = AuthRepository(
      apiClient: api,
      tokens: SessionTokens(tokenStore),
    );
    final session = SessionController(
      authRepository: auth,
      onboardingRepository: OnboardingRepository(api),
    );
    addTearDown(session.dispose);
    addTearDown(api.close);
    await session.initialize();
    expect(session.offline, isTrue);
    expect(session.account?.id, 'alice');
    await session.logout();
    expect(session.phase, SessionPhase.signedOut);
    expect(await local.bootstrap(), isNull);
  });

  testWidgets('unfinished form text and date restore without submitting', (
    tester,
  ) async {
    final local = LocalRecords(MemoryLocalStore());
    await local.bind('server', 'alice');
    await local.saveDraft('meal', '午餐', {
      'name': '米饭',
      'amount': '12.',
      'date': '2026-10-31',
    });
    final name = TextEditingController(), amount = TextEditingController();
    String? date;
    final binding = FormDraft(
      records: local,
      key: 'meal',
      label: '午餐',
      fields: {'name': name, 'amount': amount},
      isActive: () => true,
      restoreExtras: (data) => date = data['date'] as String,
    );
    await tester.pump();
    expect(name.text, '米饭');
    expect(amount.text, '12.');
    expect(date, '2026-10-31');
    expect(local.pending, isEmpty);
    name.text = '米饭半碗';
    await tester.pump();
    expect((await local.readDraft('meal'))!['name'], '米饭半碗');
    binding.dispose();
    name.dispose();
    amount.dispose();
  });
}
