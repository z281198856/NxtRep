import 'package:uuid/uuid.dart';

import '../../../core/network/api_client.dart';
import '../domain/body_models.dart';

class BodyRepository {
  BodyRepository(this._apiClient, {Uuid? uuid}) : _uuid = uuid ?? const Uuid();

  final ApiClient _apiClient;
  final Uuid _uuid;

  Future<NavyProfileDefaults> getNavyProfileDefaults() async {
    final json = expectJsonObject(
      await _apiClient.get('/profile'),
      context: '身体档案接口',
    );
    final sex = json['sex'] as String?;
    return NavyProfileDefaults(
      sex: sex == 'male' || sex == 'female' ? sex : null,
      heightCm: switch (json['height_cm']) {
        num value => value.toDouble(),
        String value => double.tryParse(value),
        _ => null,
      },
    );
  }

  Future<NavyBodyFatResult> calculateNavyBodyFat(
    NavyBodyFatInput input, {
    bool save = false,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/body/body-fat/navy',
        idempotencyKey: save ? _uuid.v4() : null,
        body: input.toJson(save: save),
      ),
      context: '美军围度法体脂估算接口',
    );
    return NavyBodyFatResult.fromJson(json);
  }

  Future<List<SavedBodyFatEstimate>> listBodyFatEstimates() async {
    final json = expectJsonObject(
      await _apiClient.get('/body/body-fat', query: const {'page_size': '20'}),
      context: '体脂估算记录接口',
    );
    return (json['list'] as List<dynamic>)
        .map(
          (item) => SavedBodyFatEstimate.fromJson(
            Map<String, dynamic>.from(item as Map),
          ),
        )
        .toList(growable: false);
  }

  Future<List<BodyMeasurement>> listMeasurements({int pageSize = 50}) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/body/measurements',
        query: {'page': '1', 'page_size': '$pageSize'},
      ),
      context: '身体测量列表接口',
    );
    return (json['list'] as List<dynamic>)
        .map((item) => BodyMeasurement.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<ProgressOverview> getOverview({required int days}) async {
    final (start, end) = _dateRange(days);
    return ProgressOverview.fromJson(
      expectJsonObject(
        await _apiClient.get(
          '/progress/overview',
          query: {'start_date': _date(start), 'end_date': _date(end)},
        ),
        context: '进展概览接口',
      ),
    );
  }

  Future<List<BodyTrendPoint>> getBodyTrend({
    required BodyMetric metric,
    required int days,
  }) async {
    final (start, end) = _dateRange(days);
    final json = expectJsonObject(
      await _apiClient.get(
        '/progress/body-trend',
        query: {
          'metric': metric.apiName,
          'start_date': _date(start),
          'end_date': _date(end),
          'window': days >= 60 ? '14d' : '7d',
        },
      ),
      context: '身体趋势接口',
    );
    return (json['points'] as List<dynamic>)
        .map((item) => BodyTrendPoint.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<List<PersonalRecord>> listPersonalRecords({int pageSize = 20}) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/progress/prs',
        query: {'page': '1', 'page_size': '$pageSize'},
      ),
      context: '个人纪录接口',
    );
    return (json['list'] as List<dynamic>)
        .map((item) => PersonalRecord.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<BodyMeasurement> createMeasurement(BodyMeasurementInput input) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/body/measurements',
        idempotencyKey: _uuid.v4(),
        body: _measurementBody(input),
      ),
      context: '新增身体测量接口',
    );
    return BodyMeasurement.fromJson(json);
  }

  Future<BodyMeasurement> updateMeasurement(
    BodyMeasurement current,
    BodyMeasurementInput input,
  ) async {
    final json = expectJsonObject(
      await _apiClient.patch(
        '/body/measurements/${current.id}',
        body: {
          ..._measurementBody(input),
          'reason': '用户修改身体测量记录',
          'expected_version': current.version,
        },
      ),
      context: '修改身体测量接口',
    );
    return BodyMeasurement.fromJson(json);
  }

  Map<String, Object?> _measurementBody(BodyMeasurementInput input) => {
    'measured_at': input.measuredAt.toUtc().toIso8601String(),
    'weight_kg': input.weightKg,
    'waist_cm': input.waistCm,
    'neck_cm': input.neckCm,
    'hip_cm': input.hipCm,
    'body_fat_percent': input.bodyFatPercent,
    'body_fat_method': input.bodyFatPercent == null ? null : 'manual',
    'source': 'manual',
    'conditions': input.conditions,
    'notes': input.notes,
  };

  (DateTime, DateTime) _dateRange(int days) {
    final now = DateTime.now();
    final end = DateTime(now.year, now.month, now.day);
    return (end.subtract(Duration(days: days - 1)), end);
  }

  String _date(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-'
      '${value.month.toString().padLeft(2, '0')}-'
      '${value.day.toString().padLeft(2, '0')}';
}
