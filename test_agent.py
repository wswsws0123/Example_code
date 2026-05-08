"""
코드 테스트 서브에이전트
- 프로젝트 내 Python 파일을 분석해 테스트를 자동 생성·실행합니다.
- 사용법: python test_agent.py [대상파일.py]
          (파일 미지정 시 프로젝트 전체를 스캔합니다)
"""

import os
import sys
import json
import glob
import subprocess
import anthropic

# ── 에이전트가 사용할 도구 정의 ──────────────────────────────────────

TOOLS = [
    {
        "name": "list_python_files",
        "description": "프로젝트 디렉터리에 있는 Python 파일 목록을 반환합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "스캔할 디렉터리 경로 (기본값: 현재 디렉터리)"
                }
            },
            "required": []
        }
    },
    {
        "name": "read_file",
        "description": "파일 내용을 읽어 반환합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "읽을 파일 경로"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_test_file",
        "description": "생성한 테스트 코드를 파일로 저장합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "저장할 파일 경로 (예: test_foo.py)"},
                "content": {"type": "string", "description": "저장할 테스트 코드"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "run_tests",
        "description": "pytest로 테스트를 실행하고 결과를 반환합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "실행할 테스트 파일 또는 디렉터리 (기본값: 현재 디렉터리)"
                }
            },
            "required": []
        }
    }
]

# ── 도구 실행기 ───────────────────────────────────────────────────────

def run_tool(name: str, inputs: dict) -> str:
    if name == "list_python_files":
        directory = inputs.get("directory", ".")
        files = [
            f for f in glob.glob(os.path.join(directory, "**", "*.py"), recursive=True)
            if "__pycache__" not in f and not os.path.basename(f).startswith("test_agent")
        ]
        if not files:
            return "Python 파일을 찾지 못했습니다."
        return "\n".join(os.path.relpath(f) for f in sorted(files))

    elif name == "read_file":
        path = inputs["path"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return f"파일을 찾을 수 없습니다: {path}"

    elif name == "write_test_file":
        path = inputs["path"]
        content = inputs["content"]
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"테스트 파일 저장 완료: {path}"

    elif name == "run_tests":
        target = inputs.get("target", ".")
        result = subprocess.run(
            ["python", "-m", "pytest", target, "-v", "--tb=short", "--no-header"],
            capture_output=True, text=True, encoding="utf-8"
        )
        output = result.stdout + result.stderr
        return output if output.strip() else "테스트 출력 없음"

    return f"알 수 없는 도구: {name}"

# ── 에이전트 루프 ─────────────────────────────────────────────────────

def run_agent(target_file: str | None = None):
    client = anthropic.Anthropic()

    scope = f"`{target_file}` 파일" if target_file else "프로젝트 전체 Python 파일"
    system_prompt = (
        "당신은 Python 코드 테스트 전문 에이전트입니다.\n"
        "주어진 코드를 분석하여 누락된 테스트를 생성하고, pytest로 실행한 뒤 결과를 보고합니다.\n"
        "테스트는 정상 케이스, 경계 케이스, 예외 케이스를 모두 포함해야 합니다.\n"
        "기존 테스트 파일이 있으면 먼저 실행해보고, 부족한 케이스를 보완하세요.\n"
        "모든 작업이 끝나면 한국어로 최종 결과를 요약해주세요."
    )
    user_message = f"{scope}을 분석하여 테스트를 생성·실행하고 결과를 보고해주세요."

    messages = [{"role": "user", "content": user_message}]

    print(f"\n{'='*60}")
    print(f"  테스트 에이전트 시작  |  대상: {scope}")
    print(f"{'='*60}\n")

    # agentic loop
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        # 텍스트 출력
        for block in response.content:
            if hasattr(block, "text") and block.text:
                print(block.text)

        # 종료 조건
        if response.stop_reason == "end_turn":
            break

        # 도구 호출 처리
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"\n[도구 호출] {block.name}({json.dumps(block.input, ensure_ascii=False)})")
                    result = run_tool(block.name, block.input)
                    print(f"[결과]\n{result[:800]}{'...' if len(result) > 800 else ''}\n")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    print(f"\n{'='*60}")
    print("  에이전트 작업 완료")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("오류: ANTHROPIC_API_KEY 환경 변수를 설정해주세요.")
        print("  예) $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        sys.exit(1)

    run_agent(target)
