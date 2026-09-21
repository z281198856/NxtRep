import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

void main() {
  testWidgets('renders an incomplete streamed bullet without throwing', (
    tester,
  ) async {
    final apiClient = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
      accessTokenProvider: () => null,
      httpClient: MockClient((_) async => throw StateError('unexpected call')),
    );
    final controller = AgentController(AgentRepository(apiClient));
    controller.messages = [
      AgentMessage(
        id: 'assistant-message',
        role: 'assistant',
        content: '- ',
        sequence: 1,
        createdAt: DateTime(2026, 9, 19),
        pending: true,
      ),
    ];
    addTearDown(controller.dispose);
    addTearDown(apiClient.close);

    await tester.pumpWidget(
      MaterialApp(home: AgentPage(controller: controller)),
    );
    await tester.pump();

    expect(tester.takeException(), isNull);
  });
}
