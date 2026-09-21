import 'dart:async';

class SseEvent {
  const SseEvent({this.id, this.event, required this.data});

  final String? id;
  final String? event;
  final String data;

  bool get isTerminal =>
      event == 'completed' || event == 'cancelled' || event == 'failed';
}

Stream<SseEvent> parseSseLines(Stream<String> lines) async* {
  String? id;
  String? event;
  final data = <String>[];

  await for (final line in lines) {
    if (line.isEmpty) {
      if (data.isNotEmpty) {
        yield SseEvent(id: id, event: event, data: data.join('\n'));
      }
      id = null;
      event = null;
      data.clear();
      continue;
    }

    if (line.startsWith(':')) {
      continue;
    }

    final separator = line.indexOf(':');
    final field = separator < 0 ? line : line.substring(0, separator);
    var value = separator < 0 ? '' : line.substring(separator + 1);
    if (value.startsWith(' ')) {
      value = value.substring(1);
    }

    switch (field) {
      case 'id':
        id = value;
      case 'event':
        event = value;
      case 'data':
        data.add(value);
    }
  }

  if (data.isNotEmpty) {
    yield SseEvent(id: id, event: event, data: data.join('\n'));
  }
}
