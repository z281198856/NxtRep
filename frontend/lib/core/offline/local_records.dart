import 'dart:async';
import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../network/api_exception.dart';
import '../state/lifecycle_notifier.dart';

abstract interface class LocalDataStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

class SecureLocalDataStore implements LocalDataStore {
  const SecureLocalDataStore();
  static const _storage = FlutterSecureStorage();
  @override
  Future<String?> read(String key) => _storage.read(key: 'nxtrep.local.$key');
  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: 'nxtrep.local.$key', value: value);
  @override
  Future<void> delete(String key) => _storage.delete(key: 'nxtrep.local.$key');
}

typedef RecordSender = Future<Object?> Function(
  String path,
  Map<String, dynamic> body,
  String key,
);

class LocalRecord {
  LocalRecord.fromJson(Map<String, dynamic> json)
    : key = json['key'] as String,
      path = json['path'] as String,
      body = Map<String, dynamic>.from(json['body'] as Map),
      createdAt = DateTime.parse(json['created_at'] as String),
      firstAttemptAt = DateTime.tryParse(
        json['first_attempt_at'] as String? ?? '',
      ),
      draftKey = json['draft_key'] as String?,
      exerciseName = json['exercise_name'] as String?,
      issue = json['issue'] as String?;

  final String key;
  final String path;
  final Map<String, dynamic> body;
  final DateTime createdAt;
  final String? draftKey;
  final String? exerciseName;
  DateTime? firstAttemptAt;
  String? issue;
  String get label {
    if (path == '/nutrition/water') return '饮水 ${body['amount_ml']} ml';
    if (path == '/body/measurements') {
      return [
        if (body['weight_kg'] != null) '体重 ${body['weight_kg']} kg',
        if (body['body_fat_percent'] != null) '体脂 ${body['body_fat_percent']}%',
      ].join(' · ').replaceAll(RegExp(r'^$'), '身体测量');
    }
    if (path.startsWith('/workouts/')) {
      return '第 ${body['set_index']} 组 · ${body['weight_kg']} kg × ${body['reps']}';
    }
    return '饮食 · ${(body['items'] as List).map((e) => e['name'] ?? '食品').join('、')}';
  }

  String get recordedAt =>
      (body['eaten_at'] ??
              body['consumed_at'] ??
              body['measured_at'] ??
              body['completed_at'])
          as String;
  Map<String, dynamic> toJson() => {
    'key': key,
    'path': path,
    'body': body,
    'created_at': createdAt.toUtc().toIso8601String(),
    'first_attempt_at': firstAttemptAt?.toUtc().toIso8601String(),
    'draft_key': draftKey,
    'exercise_name': exerciseName,
    'issue': issue,
  };
}

/// An encrypted, account-and-server-scoped write-ahead journal. Only explicit
/// create-record endpoints enter it; confirmations and AI requests never do.
class LocalRecords extends LifecycleNotifier {
  LocalRecords(this.store, {DateTime Function()? now})
    : _now = now ?? DateTime.now;
  final LocalDataStore store;
  final DateTime Function() _now;
  String? _scope;
  Map<String, dynamic> _data = {};
  final List<LocalRecord> _pending = [];
  Future<void> _tail = Future.value();
  Future<Map<String, Object?>>? _syncing;
  bool localOnly = false;
  bool usingCache = false;
  String? storageError;
  int syncRevision = 0;
  bool get bound => _scope != null;
  String? get accountScope => _scope;
  bool get syncing => _syncing != null;
  List<LocalRecord> get pending => List.unmodifiable(_pending);
  Map<String, dynamic> get drafts => Map.unmodifiable(
    Map<String, dynamic>.from(_data['drafts'] as Map? ?? {})
      ..removeWhere((key, _) => _pending.any((e) => e.draftKey == key)),
  );
  bool get needsAttention => _pending.any((e) => e.issue != null);

  void reportStorageError(String message) {
    storageError = message;
    notifyListeners();
  }

  Future<T> _locked<T>(Future<T> Function() work) async {
    final previous = _tail;
    final release = Completer<void>();
    _tail = release.future;
    await previous;
    try {
      return await work();
    } finally {
      release.complete();
    }
  }

  Future<void> bind(String server, String userId) => _locked(() async {
    final scope = base64Url.encode(utf8.encode('$server|$userId'));
    if (scope == _scope) return;
    final raw = await store.read('records.$scope');
    // Never overwrite unreadable data with an empty queue.
    final value = raw == null
        ? <String, dynamic>{'version': 1}
        : Map<String, dynamic>.from(jsonDecode(raw) as Map);
    if (value['version'] != 1) {
      throw const FormatException('Local records version');
    }
    final records = (value['pending'] as List? ?? [])
        .map((e) => LocalRecord.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
    _scope = scope;
    _data = value;
    _pending
      ..clear()
      ..addAll(records);
    usingCache = false;
    storageError = null;
    notifyListeners();
  });

  Future<void> unbind({bool forgetBootstrap = true}) => _locked(() async {
    _scope = null;
    _data = {};
    _pending.clear();
    localOnly = false;
    usingCache = false;
    if (forgetBootstrap) await store.delete('last-account');
    notifyListeners();
  });

  Future<Map<String, dynamic>?> bootstrap() async {
    final raw = await store.read('last-account');
    return raw == null
        ? null
        : Map<String, dynamic>.from(jsonDecode(raw) as Map);
  }

  Future<void> saveBootstrap(Map<String, dynamic> value) =>
      store.write('last-account', jsonEncode(value));

  static bool canRecord(String method, String path, String? key) =>
      method == 'POST' &&
      key != null &&
      ({
            '/nutrition/entries',
            '/nutrition/water',
            '/body/measurements',
          }.contains(path) ||
          RegExp(r'^/workouts/[0-9a-f-]+/sets$').hasMatch(path));

  static bool canCache(String path) =>
      path == '/workouts/active' ||
      path == '/calendar/events' ||
      path.startsWith('/nutrition/') ||
      path.startsWith('/body/') ||
      path.startsWith('/progress/') ||
      path.startsWith('/foods/') ||
      path == '/profile' ||
      path == '/settings' ||
      path == '/training/plans/active' ||
      path == '/training/templates';

  static bool transient(ApiException e) =>
      {
        'NETWORK_ERROR',
        'REQUEST_TIMEOUT',
        'INVALID_SUCCESS_RESPONSE',
        'IDEMPOTENCY_REQUEST_IN_PROGRESS',
      }.contains(e.code) ||
      (e.statusCode != null && (e.statusCode! >= 500 || e.statusCode == 429));

  String _cacheKey(String path, Map<String, String>? query) {
    final sorted = (query?.entries.toList() ?? [])
      ..sort((a, b) => a.key.compareTo(b.key));
    return '$path?${jsonEncode(Map.fromEntries(sorted))}';
  }

  Future<void> cache(String path, Map<String, String>? query, Object? value) =>
      _locked(() async {
        if (!bound) return;
        final cache = Map<String, dynamic>.from(_data['cache'] as Map? ?? {});
        cache.remove(_cacheKey(path, query));
        cache[_cacheKey(path, query)] = {
          'value': value,
          'at': _now().toUtc().toIso8601String(),
        };
        while (cache.length > 40 ||
            utf8.encode(jsonEncode(cache)).length > 400000) {
          cache.remove(cache.keys.first);
          if (cache.isEmpty) break;
        }
        _data['cache'] = cache;
        await _persist();
      });

  Object? cached(String path, Map<String, String>? query) {
    final entry = (_data['cache'] as Map?)?[_cacheKey(path, query)] as Map?;
    if (entry == null) {
      throw const ApiException(
        code: 'NETWORK_ERROR',
        message: '当前离线，此内容尚未缓存；仍可新增记录或保存草稿',
      );
    }
    usingCache = true;
    notifyListeners();
    return project(path, entry['value']);
  }

  /// Merge pending sets into the last server workout so the next set index is
  /// stable across restarts. They remain visibly pending in the journal.
  Object? project(String path, Object? value) {
    if (path != '/workouts/active' || value is! Map) return value;
    final workout = Map<String, dynamic>.from(
      jsonDecode(jsonEncode(value)) as Map,
    );
    for (final item in _pending.where(
      (e) => e.path == '/workouts/${workout['id']}/sets',
    )) {
      for (final exercise in workout['exercises'] as List) {
        if (exercise['id'] != item.body['workout_exercise_id']) continue;
        final sets = exercise['sets'] as List;
        if (sets.any(
          (e) =>
              e['client_generated_id'] == item.key ||
              e['id'] == 'local-${item.key}',
        )) {
          continue;
        }
        sets.add({...item.body, 'id': 'local-${item.key}', 'version': 0});
      }
    }
    return workout;
  }

  String? _exerciseName(String path, Map<String, dynamic> body) {
    final value =
        (_data['cache'] as Map?)?[_cacheKey(
          '/workouts/active',
          null,
        )]?['value'];
    if (value is! Map || path != '/workouts/${value['id']}/sets') return null;
    for (final exercise in value['exercises'] as List) {
      if (exercise['id'] == body['workout_exercise_id']) {
        return exercise['name_snapshot'] as String?;
      }
    }
    return null;
  }

  bool hasWorkoutPending(String path) => _pending.any(
    (e) =>
        e.path.startsWith('/workouts/') &&
        path.startsWith(e.path.replaceFirst('/sets', '')),
  );

  Future<Object?> record(
    String path,
    Map<String, dynamic> body,
    String key,
    RecordSender sender, {
    String? draftKey,
  }) async {
    await _locked(() async {
      if (!bound) {
        throw const ApiException(
          code: 'LOCAL_STORAGE_FAILED',
          message: '本地账户尚未就绪，请重新打开应用',
        );
      }
      if (_pending.length >= 500) {
        throw const ApiException(
          code: 'LOCAL_QUEUE_FULL',
          message: '待同步记录较多，请先同步或整理后继续记录',
        );
      }
      final entry = LocalRecord.fromJson({
        'key': key,
        'path': path,
        'body': jsonDecode(jsonEncode(body)),
        'draft_key': draftKey,
        'exercise_name': _exerciseName(path, body),
        'created_at': _now().toUtc().toIso8601String(),
      });
      _pending.add(entry);
      try {
        await _persist();
      } on Object {
        _pending.remove(entry);
        rethrow;
      }
      notifyListeners();
    });
    Map<String, Object?> results = {};
    try {
      results = await sync(sender);
    } on ApiException {
      // It is already durably queued even if acknowledgement storage failed.
    }
    if (results.containsKey(key)) return results[key];
    throw const ApiException(
      code: 'RECORD_SAVED_LOCALLY',
      message: '已保存在本机，待联网同步；可在“离线记录与草稿”查看',
    );
  }

  Future<Map<String, Object?>> sync(RecordSender sender) {
    final existing = _syncing;
    if (existing != null) return existing;
    if (!bound || localOnly) return Future.value({});
    final task = _flush(sender);
    _syncing = task;
    notifyListeners();
    return task.whenComplete(() {
      if (identical(_syncing, task)) _syncing = null;
      notifyListeners();
    });
  }

  Future<Map<String, Object?>> _flush(RecordSender sender) async {
    final owner = _scope;
    final results = <String, Object?>{};
    final visited = <String>{};
    while (_scope == owner && !localOnly) {
      // Never hold the storage mutex during HTTP: typing must keep saving even
      // while an acknowledgement or a slow reconnect is in flight.
      final item = await _locked<LocalRecord?>(() async {
        if (_scope != owner) return null;
        final blockedWorkouts = <String>{};
        for (final candidate in _pending) {
          final group = candidate.path.startsWith('/workouts/')
              ? candidate.path
              : null;
          if (candidate.firstAttemptAt != null &&
              _now().difference(candidate.firstAttemptAt!) >=
                  const Duration(hours: 23)) {
            candidate.issue = '上次提交已超过安全重试时限，请先核对服务端记录，避免重复';
          }
          if (candidate.issue != null) {
            if (group != null) blockedWorkouts.add(group);
            continue;
          }
          if (visited.contains(candidate.key) ||
              (group != null && blockedWorkouts.contains(group))) {
            continue;
          }
          candidate.firstAttemptAt ??= _now();
          await _persist();
          return candidate;
        }
        await _persist();
        return null;
      });
      if (item == null || _scope != owner) break;
      visited.add(item.key);
      try {
        final result = await sender(item.path, item.body, item.key);
        if (_scope != owner) break;
        await _locked(() async {
          if (_scope != owner) return;
          if (item.draftKey != null) {
            await store.delete('draft.$owner.${item.draftKey}');
            (_data['drafts'] as Map?)?.remove(item.draftKey);
          }
          final index = _pending.indexOf(item);
          _pending.remove(item);
          try {
            await _persist();
          } on Object {
            if (index >= 0) _pending.insert(index, item);
            rethrow;
          }
          results[item.key] = result;
          usingCache = false;
          syncRevision++;
        });
      } on ApiException catch (error) {
        if (_scope != owner ||
            error.isAuthenticationFailure ||
            transient(error) ||
            {
              'LOCAL_STORAGE_FAILED',
              'LOCAL_ACCOUNT_CHANGED',
            }.contains(error.code)) {
          break;
        }
        await _locked(() async {
          if (_scope != owner) return;
          item.issue = error.message;
          await _persist();
        });
      } on Object {
        storageError = '同步结果尚未安全保存在本机，记录已保留，请稍后重试';
        break;
      }
    }
    return results;
  }

  Future<void> discard(String key) => _locked(() async {
    final previous = List<LocalRecord>.of(_pending);
    _pending.removeWhere((e) => e.key == key);
    try {
      await _persist();
    } on Object {
      _pending
        ..clear()
        ..addAll(previous);
      rethrow;
    }
    notifyListeners();
  });

  Future<Map<String, dynamic>?> readDraft(String key) async {
    if (_pending.any((e) => e.draftKey == key)) return null;
    final scope = _scope;
    if (scope == null) return null;
    final raw = await store.read('draft.$scope.$key');
    return raw == null
        ? null
        : Map<String, dynamic>.from(jsonDecode(raw) as Map);
  }

  Future<void> saveDraft(
    String key,
    String label,
    Map<String, dynamic>? value, {
    String? expectedScope,
  }) => _locked(() async {
    final scope = _scope;
    if (scope == null || (expectedScope != null && scope != expectedScope)) {
      return;
    }
    if (value == null) {
      await store.delete('draft.$scope.$key');
    } else {
      final raw = jsonEncode(value);
      if (utf8.encode(raw).length > 8000000) {
        throw const ApiException(
          code: 'DRAFT_TOO_LARGE',
          message: '照片过大，无法保存草稿，请换一张较小的照片',
        );
      }
      await store.write('draft.$scope.$key', raw);
    }
    final index = Map<String, dynamic>.from(_data['drafts'] as Map? ?? {});
    if (value == null) {
      index.remove(key);
    } else {
      index[key] = {'label': label, 'at': _now().toUtc().toIso8601String()};
    }
    _data['drafts'] = index;
    await _persist();
    notifyListeners();
  });

  Future<void> _persist() async {
    if (!bound) return;
    try {
      await store.write(
        'records.$_scope',
        jsonEncode({
          ..._data,
          'pending': _pending.map((e) => e.toJson()).toList(),
        }),
      );
      storageError = null;
    } on Object {
      storageError = '本机保存失败，请保留页面内容后重试';
      notifyListeners();
      throw const ApiException(
        code: 'LOCAL_STORAGE_FAILED',
        message: '本机保存失败，请勿关闭当前内容，稍后重试',
      );
    }
  }
}
