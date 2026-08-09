"""パラメータの保存 / 既定値復帰 (1010h / 1011h)。

can / canopen を import しないこと。

HP-5143E 1010h/1011h 実測:
  - 誤って保存しないよう、決まった署名を書いたときだけ実行する。
    署名は "save" (MSB e v a s LSB) と "load" (MSB d a o l LSB)。
  - sub1 = 全パラメータ、sub2 = 通信パラメータ (1000h-1FFFh) のみ。
  - 署名が違えば abort 0800002xh、保存/復帰に失敗したら abort 06060000h。
  - 読み出しは保存機能の情報を返す。

保存先は実機の不揮発メモリ相当としてプロセス内に持つ。ファイルには書かない
(シミュレータを再起動したら工場出荷相当に戻るほうが、テストの独立性を保てる)。
"""

SAVE_SIGNATURE = 0x65766173   # "save"
LOAD_SIGNATURE = 0x64616F6C   # "load"

# 読み出し時に返す保存機能の情報。bit0 = コマンドで保存できる。
STORAGE_CAPABILITY = 0x00000001

COMMUNICATION_RANGE = (0x1000, 0x1FFF)


def is_communication_object(index):
    return COMMUNICATION_RANGE[0] <= index <= COMMUNICATION_RANGE[1]
