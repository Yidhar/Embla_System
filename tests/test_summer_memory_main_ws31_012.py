from pathlib import Path

import summer_memory.main as main_mod


def test_generate_docker_compose_uses_current_grag_config(monkeypatch, tmp_path: Path) -> None:
    template = tmp_path / "docker-compose.template.yml"
    output = tmp_path / "docker-compose.yml"
    template.write_text("auth=${NEO4J_AUTH}\ndb=${NEO4J_DB}\n", encoding="utf-8")

    monkeypatch.setattr(main_mod.runtime_config.grag, "neo4j_user", "alice")
    monkeypatch.setattr(main_mod.runtime_config.grag, "neo4j_password", "secret")
    monkeypatch.setattr(main_mod.runtime_config.grag, "neo4j_database", "embla")

    generated = main_mod.generate_docker_compose(template, output)

    assert generated == output
    assert output.read_text(encoding="utf-8") == "auth=alice/secret\ndb=embla\n"


def test_stop_managed_neo4j_container_skips_unmanaged(monkeypatch) -> None:
    monkeypatch.setattr(main_mod, "_MANAGED_NEO4J_STARTED", False)
    called = []
    monkeypatch.setattr(main_mod.subprocess, "run", lambda *args, **kwargs: called.append((args, kwargs)))

    stopped = main_mod.stop_managed_neo4j_container()

    assert stopped is False
    assert called == []


def test_render_graph_visualization_delegates_to_visualizer(monkeypatch, tmp_path: Path) -> None:
    expected = tmp_path / "graph.html"
    monkeypatch.setattr(main_mod, "visualize_quintuples", lambda auto_open=True: expected)

    result = main_mod.render_graph_visualization(auto_open=False)

    assert result == expected
