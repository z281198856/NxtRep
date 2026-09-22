import 'package:uuid/uuid.dart';

import '../../../core/network/api_client.dart';
import '../domain/exercise_models.dart';

class ExerciseRepository {
  ExerciseRepository(this._apiClient, {Uuid? uuid})
    : _uuid = uuid ?? const Uuid();

  final ApiClient _apiClient;
  final Uuid _uuid;

  Future<ExercisePageData> list({
    String? keyword,
    String? equipment,
    String? muscle,
  }) async {
    final query = <String, String>{'page': '1', 'page_size': '100'};
    if (keyword != null && keyword.trim().isNotEmpty) {
      query['keyword'] = keyword.trim();
    }
    if (equipment != null && equipment.isNotEmpty) {
      query['equipment'] = equipment;
    }
    if (muscle != null && muscle.isNotEmpty) query['muscle'] = muscle;
    final json = expectJsonObject(
      await _apiClient.get('/exercises', query: query),
      context: '动作库接口',
    );
    return ExercisePageData.fromJson(json);
  }

  Future<ExerciseDetail> getDetail(String id) async {
    final json = expectJsonObject(
      await _apiClient.get('/exercises/$id'),
      context: '动作详情接口',
    );
    return ExerciseDetail.fromJson(json);
  }

  Future<List<ExerciseHistoryItem>> getHistory(String id) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/exercises/$id/history',
        query: const {'limit': '10'},
      ),
      context: '动作训练历史接口',
    );
    return (json['history'] as List<dynamic>)
        .map(
          (item) => ExerciseHistoryItem.fromJson(
            Map<String, dynamic>.from(item as Map),
          ),
        )
        .toList(growable: false);
  }

  Future<ExerciseDetail> create(CustomExerciseInput input) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/exercises',
        idempotencyKey: _uuid.v4(),
        body: input.toJson(),
      ),
      context: '新增自定义动作接口',
    );
    return ExerciseDetail.fromJson(json);
  }

  Future<ExerciseDetail> update(
    ExerciseDetail exercise,
    CustomExerciseInput input,
  ) async {
    final json = expectJsonObject(
      await _apiClient.patch(
        '/exercises/${exercise.id}',
        body: {...input.toJson(), 'expected_version': exercise.version},
      ),
      context: '编辑自定义动作接口',
    );
    return ExerciseDetail.fromJson(json);
  }

  Future<void> delete(ExerciseDetail exercise) => _apiClient
      .request(
        'DELETE',
        '/exercises/${exercise.id}',
        query: {'expected_version': '${exercise.version}'},
      )
      .then((_) {});
}
