# Operate one workspace with admitted creators

The single-company workspace boundary is superseded by [ADR 0009](0009-multiple-workspaces.md) for the multi-workspace design. The original pilot assumptions below describe the existing implementation.

The pilot runs in a cloud account controlled by the operator and serves one company workspace with a small, explicitly admitted group of creators; other workspace members can use shared apps. Company approval is assumed to cover this hosting arrangement. Generated code is treated as potentially faulty, including accidental attempts to access other apps' data, so admitting creators does not remove the need for execution and data isolation. Company-owned deployment is deferred.
