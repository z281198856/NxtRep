import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';
import 'package:nxtrep/core/offline/local_records.dart';
import 'package:nxtrep/core/offline/local_records_page.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/exercises/data/exercise_repository.dart';
import 'package:nxtrep/features/nutrition/data/nutrition_repository.dart';
import 'package:nxtrep/features/nutrition/domain/nutrition_models.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_controller.dart';
import 'package:nxtrep/features/nutrition/presentation/nutrition_photo_page.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';
import 'package:nxtrep/features/progress/data/body_repository.dart';
import 'package:nxtrep/features/progress/domain/body_models.dart';
import 'package:nxtrep/features/progress/presentation/progress_controller.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/presentation/training_controller.dart';

const _phase = String.fromEnvironment('OFFLINE_PHASE', defaultValue: 'write');
const _dateValue = String.fromEnvironment('OFFLINE_DATE');
const _storage = FlutterSecureStorage();

class _TestStore implements LocalDataStore {
  const _TestStore();
  static const _prefix = 'nxtrep.offline-device.';
  @override
  Future<String?> read(String key) => _storage.read(key: '$_prefix$key');
  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: '$_prefix$key', value: value);
  @override
  Future<void> delete(String key) => _storage.delete(key: '$_prefix$key');
}

class _TestTokens implements RefreshTokenStore {
  static const _key = 'nxtrep.offline-device.refresh';
  @override
  Future<String?> read() => _storage.read(key: _key);
  @override
  Future<void> write(String value) => _storage.write(key: _key, value: value);
  @override
  Future<void> delete() => _storage.delete(key: _key);
}

class _Connection extends http.BaseClient {
  final _inner = http.Client();
  bool offline = _phase == 'recover';
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    if (offline) {
      throw const ApiException(
        code: 'NETWORK_ERROR',
        message: 'device test offline',
      );
    }
    return _inner.send(request);
  }

  @override
  void close() => _inner.close();
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('persistent offline records and photo draft: $_phase', (
    tester,
  ) async {
    final date = DateTime.parse(_dateValue);
    if (_phase == 'write') {
      for (final key in (await _storage.readAll()).keys.where(
        (k) => k.startsWith(_TestStore._prefix),
      )) {
        await _storage.delete(key: key);
      }
    }
    final local = LocalRecords(const _TestStore());
    final connection = _Connection();
    final tokens = SessionTokens(_TestTokens());
    final api = ApiClient(
      config: ApiConfig(),
      accessTokenProvider: () => tokens.accessToken,
      httpClient: connection,
    )..localRecords = local;
    final auth = AuthRepository(apiClient: api, tokens: tokens);
    api.tokenRefresher = auth.refreshSession;
    final session = SessionController(
      authRepository: auth,
      onboardingRepository: OnboardingRepository(api),
    );
    await session.initialize();
    if (_phase == 'write') {
      await session.login(
        const String.fromEnvironment('E2E_USERNAME'),
        const String.fromEnvironment('E2E_PASSWORD'),
      );
      expect(session.phase, SessionPhase.authenticated);
      final repository = TrainingRepository(api);
      final exercises = await ExerciseRepository(api).list();
      final started = await repository.startWorkout(null);
      await repository.addExercise(
        workout: started,
        exerciseId: exercises.items.first.id,
      );
      final workout = (await repository.getActiveWorkout())!;
      final training = TrainingController(repository)..activeWorkout = workout;
      final nutrition = NutritionController(NutritionRepository(api));
      final progress = ProgressController(BodyRepository(api));
      await api.get('/nutrition/water', query: {'date': _dateValue});
      connection.offline = true;
      local.localOnly = true;
      expect(
        await training.completeSet(
          exercise: workout.exercises.first,
          weightKg: 20,
          reps: 8,
        ),
        isTrue,
      );
      expect(training.activeWorkout!.completedSetCount, 1);
      expect(
        await nutrition.addWater(
          321,
          DateTime(date.year, date.month, date.day, 10),
        ),
        isTrue,
      );
      expect(
        await progress.add(
          BodyMeasurementInput(
            measuredAt: DateTime(date.year, date.month, date.day, 9),
            weightKg: 71.2,
          ),
        ),
        isTrue,
      );
      expect(
        await nutrition.add(
          const ManualNutritionInput(
            name: '离线验收米饭',
            mealType: 'lunch',
            amountG: 100,
            kcal: 130,
            proteinG: 2,
            carbsG: 28,
            fatG: 0.3,
            isFlexibleMeal: false,
          ),
          date: date,
        ),
        isTrue,
      );
      expect(local.pending.length, 4);
      training.dispose();
      nutrition.dispose();
      progress.dispose();
    } else {
      expect(session.phase, SessionPhase.authenticated);
      expect(session.offline, isTrue);
      expect(local.pending.length, 4);
      final workout = await TrainingRepository(api).getActiveWorkout();
      expect(workout!.completedSetCount, 1);
      expect(workout.exercises.first.sets.single.id, startsWith('local-'));
    }
    await tester.pumpWidget(
      NxtRepApp(sessionController: session, onDispose: api.close),
    );
    await _wait(tester, find.text('我的'));
    final nutrition = NutritionController(NutritionRepository(api));
    final context = tester.element(find.text('我的').last);
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => NutritionPhotoPage(
          controller: nutrition,
          recordDate: date,
          imageBytesPicker: (_) async => base64Decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
          ),
        ),
      ),
    );
    await _wait(tester, find.text('拍照记一餐'));
    if (_phase == 'write') {
      await tester.tap(find.text('相册'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, '留到重启后再识别');
      await tester.pumpAndSettle();
      expect(
        (await local.readDraft('photo:${date.toIso8601String()}'))!['notes'],
        '留到重启后再识别',
      );
    } else {
      await _wait(tester, find.text('留到重启后再识别'));
      expect(find.byType(Image), findsWidgets);
      expect(find.text('AI 估算预览'), findsNothing);
      Navigator.of(tester.element(find.text('拍照记一餐'))).pop();
      await tester.pumpAndSettle();
      connection.offline = false;
      await session.reconnectAndSync();
      expect(session.offline, isFalse);
      expect(local.pending, isEmpty);
      await api.syncLocalRecords();
      final water = await NutritionRepository(api).listWater(date);
      expect(water.where((e) => e.amountMl == 321).length, 1);
      final meals = await NutritionRepository(api).listEntries(date);
      expect(meals.where((e) => e.displayName == '离线验收米饭').length, 1);
      expect(
        (await BodyRepository(
          api,
        ).listMeasurements()).where((e) => e.weightKg == 71.2).length,
        1,
      );
      expect(
        (await TrainingRepository(api).getActiveWorkout())!.completedSetCount,
        1,
      );
      await tester.tap(find.text('我的').last);
      await _wait(tester, find.text('离线记录与草稿'));
      await tester.ensureVisible(find.text('离线记录与草稿'));
      await tester.tap(find.text('离线记录与草稿'));
      await _wait(tester, find.byType(LocalRecordsPage));
      expect(find.text('待同步 0 条'), findsOneWidget);
    }
    await tester.pumpWidget(const SizedBox());
    nutrition.dispose();
    local.dispose();
    if (_phase == 'recover') {
      for (final key in (await _storage.readAll()).keys.where(
        (k) => k.startsWith(_TestStore._prefix),
      )) {
        await _storage.delete(key: key);
      }
    }
  });
}

Future<void> _wait(WidgetTester tester, Finder finder) async {
  for (var i = 0; i < 120; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    if (finder.evaluate().isNotEmpty) {
      await tester.pump(const Duration(milliseconds: 400));
      return;
    }
  }
  fail('Offline device operation did not settle');
}
