import 'dart:async';

import 'package:flutter/material.dart';

import 'local_records.dart';

class LocalRecordsScope extends InheritedWidget {
  const LocalRecordsScope({
    super.key,
    required this.records,
    required super.child,
  });
  final LocalRecords? records;
  static LocalRecords? read(BuildContext context) =>
      context.getInheritedWidgetOfExactType<LocalRecordsScope>()?.records;
  @override
  bool updateShouldNotify(LocalRecordsScope oldWidget) =>
      records != oldWidget.records;
}

/// Saves raw text, including unfinished/invalid input, without submitting it.
class FormDraft {
  FormDraft({
    required this.records,
    required this.key,
    required this.label,
    required this.fields,
    required this.isActive,
    this.extras,
    this.restoreExtras,
    this.onRestored,
  }) : _owner = records?.accountScope {
    for (final field in fields.values) {
      field.addListener(save);
    }
    unawaited(_restore());
  }
  final LocalRecords? records;
  final String key;
  final String label;
  final Map<String, TextEditingController> fields;
  final bool Function() isActive;
  final Map<String, dynamic> Function()? extras;
  final void Function(Map<String, dynamic>)? restoreExtras;
  final VoidCallback? onRestored;
  final String? _owner;
  bool _restoring = false;
  bool _edited = false;
  bool _closed = false;
  bool suspended = false;

  Future<void> _restore() async {
    try {
      final data = await records?.readDraft(key);
      if (data == null ||
          _closed ||
          !isActive() ||
          _edited ||
          records?.accountScope != _owner) {
        return;
      }
      _restoring = true;
      for (final entry in fields.entries) {
        if (data[entry.key] is String) {
          entry.value.text = data[entry.key] as String;
        }
      }
      restoreExtras?.call(data);
      _restoring = false;
      onRestored?.call();
    } on Object {
      records?.reportStorageError('草稿读取失败，原草稿已保留，请稍后重试');
    }
  }

  void save() {
    if (suspended ||
        _restoring ||
        _closed ||
        !isActive() ||
        records?.accountScope != _owner) {
      return;
    }
    _edited = true;
    final value = <String, dynamic>{
      for (final entry in fields.entries) entry.key: entry.value.text,
      ...?extras?.call(),
    };
    unawaited(
      records?.saveDraft(key, label, value, expectedScope: _owner).catchError((
        Object _,
      ) {
        records?.reportStorageError('草稿保存失败，请保留当前内容后重试');
      }),
    );
  }

  void dispose() {
    _closed = true;
    for (final field in fields.values) {
      field.removeListener(save);
    }
  }
}

Future<void> clearSubmittedDraft(BuildContext context, String key) async {
  final records = LocalRecordsScope.read(context);
  try {
    await records?.saveDraft(
      key,
      '',
      null,
      expectedScope: records.accountScope,
    );
  } on Object {
    records?.reportStorageError('记录已保存，草稿清理失败；再次提交前请先核对记录');
  }
}
