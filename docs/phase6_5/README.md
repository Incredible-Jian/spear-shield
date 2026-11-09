# Phase 6.5 最终执行审计

执行日期：2026-11-03。本目录对应负责人提供的最终执行版任务书；Phase 6.5 是阶段编号，不是软件版本号。冻结口径仍为 `delegated-2026-11-03-v1`，未进入 Phase 7。

**总状态：PARTIAL。** 审计执行、局部修复和证据整理已完成；发现的阻塞项并未因此通过验收。

- [A–I 最终报告](audit_report.md)
- [33 项定义逐项审计](operational_definition_audit.md)、[机器映射](manifests/definition_mapping.json)
- [缺失数据审计及修复记录](missing_data_audit.md)
- [回测完整性审计及修复记录](backtest_integrity_audit.md)
- [反向溯源审计](data_lineage_audit.md)
- [版权与隐私审计](copyright_and_privacy_audit.md)
- [冻结清单](manifests/phase6_5_manifest.json)、[真实回放证据](manifests/replay_evidence.json)
- [发布检查清单](release_checklist.md)

机器清单按实际文件字节计算 SHA256；不能把哈希视为数据版权许可、历史实际发布时间证明或策略有效性证明。原始行情、第三方全文和本机数据库不随本目录交付。

复核命令（项目根目录）：

```powershell
python -m pytest --ignore=tests/integration/test_akshare_provider.py -q --basetemp=cache/phase65/pytest-review
python scripts/audit_phase65_replay.py
python scripts/audit_phase65_network.py
```

真实审计测试需要本机已有、通过哈希校验的研究缓存；缺缓存明确 skip，不会换成合成行情。网络脚本逐项 40 秒限时，与离线测试分开计数。每次回放创建新报告目录，保留历史报告。报告聚合证据会更新，重新冻结时应再次生成清单。
