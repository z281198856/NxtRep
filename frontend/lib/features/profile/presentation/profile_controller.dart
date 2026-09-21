import 'package:flutter/foundation.dart';

import '../../../core/network/api_exception.dart';
import '../data/profile_repository.dart';
import '../domain/profile_models.dart';

class ProfileController extends ChangeNotifier {
  ProfileController(this._repository);

  final ProfileDataSource _repository;

  UserProfile? profile;
  TrainingPreferences? trainingPreferences;
  AppSettings? settings;
  bool loading = false;
  bool saving = false;
  String? errorMessage;

  bool get ready =>
      profile != null && trainingPreferences != null && settings != null;

  Future<void> refresh() async {
    if (loading) return;
    loading = true;
    errorMessage = null;
    notifyListeners();
    try {
      final results = await Future.wait<Object>([
        _repository.getProfile(),
        _repository.getTrainingPreferences(),
        _repository.getSettings(),
      ]);
      profile = results[0] as UserProfile;
      trainingPreferences = results[1] as TrainingPreferences;
      settings = results[2] as AppSettings;
    } on ApiException catch (error) {
      errorMessage = _message(error);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<bool> savePersonal(PersonalProfileInput input) async {
    final current = profile;
    if (saving || current == null) return false;
    saving = true;
    errorMessage = null;
    notifyListeners();
    try {
      profile = await _repository.updatePersonalProfile(current, input);
      return true;
    } on ApiException catch (error) {
      errorMessage = _message(error);
      return false;
    } finally {
      saving = false;
      notifyListeners();
    }
  }

  Future<bool> saveTraining(TrainingPreferencesInput input) async {
    final currentProfile = profile;
    final currentPreferences = trainingPreferences;
    if (saving || currentProfile == null || currentPreferences == null) {
      return false;
    }
    saving = true;
    errorMessage = null;
    notifyListeners();
    try {
      final result = await _repository.updateTrainingPreferences(
        currentProfile,
        currentPreferences,
        input,
      );
      profile = result.profile;
      trainingPreferences = result.preferences;
      return true;
    } on ApiException catch (error) {
      errorMessage = _message(error);
      return false;
    } finally {
      saving = false;
      notifyListeners();
    }
  }

  Future<bool> saveSettings(AppSettingsInput input) async {
    final current = settings;
    if (saving || current == null) return false;
    saving = true;
    errorMessage = null;
    notifyListeners();
    try {
      settings = await _repository.updateSettings(current, input);
      return true;
    } on ApiException catch (error) {
      errorMessage = _message(error);
      return false;
    } finally {
      saving = false;
      notifyListeners();
    }
  }

  static String _message(ApiException error) => switch (error.code) {
    'PROFILE_VERSION_CONFLICT' ||
    'GOALS_VERSION_CONFLICT' ||
    'SETTINGS_VERSION_CONFLICT' => '资料已在其他位置更新，请刷新后再保存',
    'GOAL_CHECK_FAILED' => error.message,
    _ => error.message,
  };
}
