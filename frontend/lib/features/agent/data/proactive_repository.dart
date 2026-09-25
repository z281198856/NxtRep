import '../../../core/network/api_client.dart';
import '../domain/proactive_models.dart';

class ProactiveRepository {
  ProactiveRepository(this._apiClient);

  final ApiClient _apiClient;

  Future<ProactiveSettings> getSettings() async => ProactiveSettings.fromJson(
    expectJsonObject(
      await _apiClient.get('/notification-settings'),
      context: '主动管理设置接口',
    ),
  );

  Future<ProactiveSettings> setEnabled(
    ProactiveSettings current,
    bool enabled,
  ) async => ProactiveSettings.fromJson(
    expectJsonObject(
      await _apiClient.patch(
        '/notification-settings',
        body: {
          'enabled': enabled ? true : current.enabled,
          'categories': {...current.categories, 'proactive_coach': enabled},
          if (enabled && current.version == 1) 'frequency': 'daily',
          'expected_version': current.version,
        },
      ),
      context: '更新主动管理设置接口',
    ),
  );

  Future<ProactiveSettings> setFrequency(
    ProactiveSettings current,
    String frequency,
  ) async => ProactiveSettings.fromJson(
    expectJsonObject(
      await _apiClient.patch(
        '/notification-settings',
        body: {'frequency': frequency, 'expected_version': current.version},
      ),
      context: '更新主动建议范围接口',
    ),
  );

  Future<void> review() async {
    await _apiClient.post('/agent/proactive/review');
  }

  Future<List<ProactiveNotice>> listUnread() async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/notifications',
        query: {
          'unread_only': 'true',
          'page': '1',
          'page_size': '20',
          'category': 'proactive_coach',
        },
      ),
      context: '主动建议列表接口',
    );
    return (json['list'] as List<dynamic>? ?? const [])
        .where((item) => (item as Map)['category'] == 'proactive_coach')
        .map(
          (item) =>
              ProactiveNotice.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .toList(growable: false);
  }

  Future<void> markRead(String id) async {
    await _apiClient.post('/notifications/$id/read');
  }

  Future<ProactiveNotice> submitFeedback(String id, String rating) async =>
      ProactiveNotice.fromJson(
        expectJsonObject(
          await _apiClient.put(
            '/agent/proactive/notices/$id/feedback',
            body: {'rating': rating},
          ),
          context: '主动建议反馈接口',
        ),
      );
}
