import streamlit as st
import anthropic
from PIL import Image
import base64
import io
import mimetypes
import pandas as pd
from datetime import datetime

# --- Constants ---
CLAUDE_MODEL = "claude-3-sonnet-20240229"
VALID_FILE_TYPES = ["png", "jpg", "jpeg", "webp", "xlsx"]

# --- Avatar SVGs ---
USER_AVATAR = "data:image/svg+xml;base64," + base64.b64encode('''
<svg width="5" height="5" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="12" cy="12" r="10" stroke="black" stroke-width="2" fill="white"/>
</svg>
'''.encode('utf-8')).decode('utf-8')

ASSISTANT_AVATAR = "data:image/svg+xml;base64," + base64.b64encode('''
<svg width="5" height="5" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="12" cy="12" r="10" stroke="black" stroke-width="2" fill="black"/>
</svg>
'''.encode('utf-8')).decode('utf-8')


def init_anthropic_client(api_key):
    """Anthropicクライアントを初期化する"""
    try:
        if not api_key:
            st.error("API Keyが設定されていません。")
            st.stop()
        return anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        st.error(f"Anthropic クライアントの初期化に失敗しました: {str(e)}")
        st.stop()


def stream_response(client, messages):
    """APIからのレスポンスを処理する"""
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=messages
        )

        if response.content:
            return response.content[0].text
        return None
    except Exception as e:
        st.error(f"応答の取得中にエラーが発生しました: {str(e)}")
        return None


def convert_image_to_base64(file, max_size_mb=5):
    """画像ファイルをbase64文字列に変換する"""
    max_size_bytes = max_size_mb * 1024 * 1024

    try:
        image = Image.open(file)
        img_format = image.format

        quality = 90
        resize_factor = 0.9
        min_quality = 20
        min_dimension = 200

        while True:
            img_bytes = io.BytesIO()

            if img_format in ["JPEG", "JPG"]:
                image.save(img_bytes, format='JPEG', quality=quality, optimize=True)
            else:
                if img_format != "PNG":
                    image = image.convert("RGB")
                image.save(img_bytes, format='PNG' if img_format == "PNG" else 'JPEG',
                           quality=quality if img_format != "PNG" else None,
                           optimize=True)

            if (img_bytes.tell() * 4 / 3) <= max_size_bytes:
                break

            if img_format in ["JPEG", "JPG"] and quality > min_quality:
                quality -= 10
            else:
                new_width = int(image.width * resize_factor)
                new_height = int(image.height * resize_factor)

                if new_width < min_dimension or new_height < min_dimension:
                    st.warning("画像を十分に圧縮できませんでした。")
                    return None

                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        return base64.b64encode(img_bytes.getvalue()).decode('utf-8')

    except Exception as e:
        st.error(f"画像の処理中にエラーが発生しました: {str(e)}")
        return None


def prepare_messages(messages, uploaded_file=None):
    """メッセージを整形してAPIに送信できる形式にする"""
    prepared_messages = []

    for msg in messages:
        if msg["role"] == "user":
            content = msg["content"]
            prepared_messages.append({"role": msg["role"], "content": content})
        else:
            prepared_messages.append(msg)

    if uploaded_file and prepared_messages:
        mime_type = uploaded_file.type

        if mime_type.startswith('image/'):
            image_data = convert_image_to_base64(uploaded_file)
            if image_data:
                last_message = prepared_messages[-1]
                if last_message["role"] == "user":
                    last_content = last_message["content"]
                    last_message["content"] = [{
                        "type": "text",
                        "text": last_content
                    }, {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_data
                        }
                    }]

        elif mime_type in ['application/vnd.ms-excel',
                           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
            try:
                df = pd.read_excel(uploaded_file)
                df_string = df.to_string(index=False)
                last_message = prepared_messages[-1]
                if last_message["role"] == "user":
                    last_content = last_message["content"]
                    last_message["content"] = [{
                        "type": "text",
                        "text": last_content
                    }, {
                        "type": "text",
                        "text": f"```\n{df_string}\n```"
                    }]
            except Exception as e:
                st.error(f"Excelファイルの処理中にエラーが発生しました: {str(e)}")

    return prepared_messages


def main():
    # セッションステートの初期化
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # サイドバーのコンポーネント
    with st.sidebar:
        api_key = st.text_input("input your name", type="password")

        st.divider()

        uploaded_file = st.file_uploader(
            "upload image or Excel file",
            type=VALID_FILE_TYPES,
            help="画像(.png, .jpg, .jpeg, .webp)またはExcel(.xlsx)ファイルをアップロード"
        )

        st.divider()

        if st.button("Clear"):
            st.session_state.messages = []
            st.rerun()

    # Anthropicクライアントの初期化
    if api_key:
        client = init_anthropic_client(api_key)
    else:
        st.warning("APIキーを入力してください")
        st.stop()

    # チャット履歴の表示
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=USER_AVATAR if message["role"] == "user" else ASSISTANT_AVATAR):
            st.markdown(message["content"] if isinstance(message["content"], str) else str(message["content"]))

    # ユーザー入力の処理
    if prompt := st.chat_input("メッセージを入力..."):
        # ユーザーメッセージをセッションに追加
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar=USER_AVATAR):
            st.markdown(prompt)

        # アシスタントの応答を処理
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            try:
                prepared_messages = prepare_messages(st.session_state.messages, uploaded_file)
                message = stream_response(client, prepared_messages)

                if message:
                    st.markdown(message, unsafe_allow_html=True)
                    st.session_state.messages.append({"role": "assistant", "content": message})

            except Exception as e:
                st.error(f"エラーが発生しました: {str(e)}")


if __name__ == "__main__":
    main()