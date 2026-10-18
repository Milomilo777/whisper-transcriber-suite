<div align="center">

<img src="../img/promo-hero.svg" alt="Whisper Transcriber Suite: sound in, text out. Free, open-source transcription that runs Whisper on your own computer." width="100%">

# Whisper Transcriber Suite

**Phiên âm và tạo phụ đề miễn phí, ngoại tuyến cho các bản ghi âm dài bằng ngôn ngữ của bạn — chạy ngay trên máy tính xách tay thông thường, không cần tài khoản và không tải tệp âm thanh của bạn lên.**

[![CI](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/Milomilo777/whisper-transcriber-suite/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/Milomilo777/whisper-transcriber-suite?label=release&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-green.svg)](../../LICENSE)

### [Tải xuống cho Windows](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)

macOS và Linux: xem [Download](#download).

<!-- language-links:start -->

<p>
<a href="../../README.md">English</a> ·
<a href="README.de.md">Deutsch</a> ·
<a href="README.fr.md">Français</a> ·
<a href="README.es.md">Español</a> ·
<a href="README.it.md">Italiano</a> ·
<a href="README.pt-BR.md">Português (Brasil)</a> ·
<a href="README.pt.md">Português (Portugal)</a> ·
<a href="README.nl.md">Nederlands</a> ·
<a href="README.pl.md">Polski</a> ·
<a href="README.ru.md">Русский</a> ·
<a href="README.uk.md">Українська</a> ·
<a href="README.tr.md">Türkçe</a> ·
<a href="README.cs.md">Čeština</a> ·
<a href="README.sk.md">Slovenčina</a> ·
<a href="README.hu.md">Magyar</a> ·
<a href="README.ro.md">Română</a> ·
<a href="README.bg.md">Български</a> ·
<a href="README.el.md">Ελληνικά</a> ·
<a href="README.sv.md">Svenska</a> ·
<a href="README.da.md">Dansk</a> ·
<a href="README.nb.md">Norsk bokmål</a> ·
<a href="README.fi.md">Suomi</a> ·
<a href="README.hr.md">Hrvatski</a> ·
<a href="README.sr.md">Српски</a> ·
<a href="README.sl.md">Slovenščina</a> ·
<a href="README.lt.md">Lietuvių</a> ·
<a href="README.zh-CN.md">简体中文</a> ·
<a href="README.zh-TW.md">繁體中文</a> ·
<a href="README.ja.md">日本語</a> ·
<a href="README.ko.md">한국어</a> ·
<b>Tiếng Việt</b> ·
<a href="README.th.md">ไทย</a> ·
<a href="README.id.md">Bahasa Indonesia</a> ·
<a href="README.ms.md">Bahasa Melayu</a> ·
<a href="README.hi.md">हिन्दी</a> ·
<a href="README.ar.md">العربية</a> ·
<a href="README.fa.md">فارسی</a> ·
<a href="README.he.md">עברית</a> ·
<a href="README.lv.md">Latviešu</a> ·
<a href="README.ca.md">Català</a> ·
<a href="README.bn.md">বাংলা</a> ·
<a href="README.fil.md">Filipino</a>
</p>

<!-- language-links:end -->
<!-- translated from README.md at commit 66585d5 -->

</div>

## Dành cho ai

Dành cho những người làm phụ đề, biên dịch viên, nhà nghiên cứu và nhà báo muốn chuyển đổi các bản ghi âm dài
(phỏng vấn, bài giảng, bài phát biểu, video) thành văn bản hoặc phụ đề.
Chỉ cần kéo thả tệp âm thanh hoặc video vào, bản phiên âm sẽ được ghi lại ngay bên cạnh. Công cụ xử lý giọng nói chạy ngay trên máy tính của bạn, vì vậy
không có phí tính theo phút và, khi mô hình đã được tải xuống, bạn sẽ không cần kết nối internet nữa.

<div align="center">
<img src="../img/screenshot-transcribe.png" alt="Tab Transcribe: vùng thả tệp, bộ chọn công cụ và ngôn ngữ, các tùy chọn nhãn người nói và dấu thời gian theo từng từ" width="80%">
</div>

## Tính năng mới trong bản 2.0

- **Tốc độ và thời gian còn lại:** Tab Queue hiển thị tốc độ xử lý của từng công việc và thời gian ước tính còn lại.
- **Video có phụ đề từ liên kết:** tải xuống, phiên âm và gắn cứng (burn) phụ đề vào video thành một công việc duy nhất ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Bản phiên âm dưới dạng trang web:** tạo một tệp `.html` với khả năng tìm kiếm và nhấp để phát âm thanh, hoạt động ngoại tuyến trên bất kỳ trình duyệt nào.
- **Chế độ làm việc ngoại tuyến có thể kiểm tra:** khi bật Work offline, thanh trạng thái hiển thị liệu ứng dụng hoặc tiến trình do nó khởi chạy có đang kết nối mạng hay không.
- **Dịch sang tiếng Anh:** chuyển đổi giọng nói không phải tiếng Anh thành phụ đề tiếng Anh chỉ trong một lần chạy.
- **Bắt đầu nhanh:** ở lần cài đặt đầu tiên, ứng dụng sẽ hỏi ba câu hỏi và cung cấp một video mẫu 18 giây để hiển thị kết quả ngay lập tức.
- **Báo cáo sự cố** từ trình đơn Help mà không cần tài khoản GitHub.
- **macOS:** có trình đơn ứng dụng với Settings (Command-comma), chế độ sáng/tối tự thay đổi theo hệ thống, và thông báo. **Windows:** hiển thị tiến trình trên thanh tác vụ và thanh tiêu đề chế độ tối.

Danh sách đầy đủ: [CHANGELOG](../CHANGELOG.md).

## Tính năng nổi bật

- **Các công cụ chạy cục bộ:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (mặc định), whisper.cpp và NVIDIA Parakeet, hỗ trợ nhiều ngôn ngữ mà Whisper
  có thể nhận dạng. Ứng dụng ưu tiên sử dụng GPU NVIDIA
  thông qua CUDA khi khả dụng, nếu không sẽ dùng CPU.
- **Ứng dụng bằng ngôn ngữ của bạn:** Menu, nút và thông báo có trong 42 ngôn ngữ
  (dịch máy và được đánh dấu như vậy; rất hoan nghênh các góp ý sửa lỗi). Ứng dụng
  theo ngôn ngữ hệ thống của bạn, hoặc bạn có thể chọn một ngôn ngữ trong Cài đặt
  nâng cao. Tiếng Ba Tư, tiếng Ả Rập và tiếng Do Thái hiện có trên Windows.
- **14 định dạng đầu ra:** SRT, VTT, ASS, TSV, TXT, JSON, LRC, Markdown, DOCX và
  PDF, cộng thêm các định dạng oTranscribe, ELAN, InqScribe và Express Scribe. DOCX
  và PDF hỗ trợ vẽ mọi hệ chữ cái, bao gồm tiếng Ba Tư, tiếng Ả Rập và tiếng Urdu được viết từ phải sang trái với các chữ cái nối liền.
- **Trang web dễ dàng chia sẻ:** lưu bản phiên âm hoàn chỉnh dưới dạng một tệp `.html`
  có thể hoạt động ngoại tuyến trên mọi trình duyệt; nhấp vào một từ để nghe, tìm kiếm, hoặc chuyển đến các chương.
- **Nhãn người nói** mà không cần tài khoản Hugging Face, cùng tính năng đánh dấu thời gian cho từng từ và cắt đoạn thời gian.
- **Tiếp tục công việc bị gián đoạn** từ điểm lưu cuối cùng thay vì phải bắt đầu lại từ đầu
  (với công cụ mặc định).
- **Video trực tuyến:** tải xuống từ bất kỳ trang web nào mà [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  hỗ trợ và phiên âm ngay khi tải xong.
- **Liên kết đến video có phụ đề:** chỉ một dấu tích sẽ chuyển liên kết thành một video `<title>-subbed.mp4`
  đã gắn cứng phụ đề: kết hợp tải xuống, phiên âm và gắn cứng phụ đề trong một công việc duy nhất
  ([../SUBTITLED_VIDEO.md](../SUBTITLED_VIDEO.md)).
- **Trực tiếp (Live):** phiên âm từ micrô, hoặc âm thanh hệ thống trên Windows, ngay khi âm thanh đang phát
  ([../LIVE.md](../LIVE.md)).
- **Hàng đợi hàng loạt và thư mục theo dõi** cho nhiều tệp cùng lúc.
- **Chế độ mạng nội bộ:** cung cấp một trang web phiên âm và một API tương thích OpenAI cho
  các thiết bị khác trong mạng lưới của bạn ([../SERVER.md](../SERVER.md)).
- **Tùy chọn, mặc định tắt:** Công cụ AI cho bản phiên âm hoàn chỉnh (tóm tắt,
  câu hỏi, SRT song ngữ), và tính năng chuyển văn bản thành giọng nói ngoại tuyến với khả năng sao chép giọng nói.

So sánh ứng dụng này với Subtitle Edit, Vibe, Buzz, noScribe và aTrain,
bao gồm cả trường hợp khi nào một ứng dụng khác sẽ là lựa chọn tốt hơn:
**[../COMPARISON.md](../COMPARISON.md)**.

<a id="download"></a>

## Tải xuống

Phiên bản mới nhất: **[trang releases](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest)**.

| Tệp | Dành cho |
|---|---|
| `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` | Windows 10 hoặc 11, 64-bit. Hầu hết mọi người cần tải tệp này. |
| `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` | Windows, không cần cài đặt: chỉ cần giải nén và chạy. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-arm64.dmg` | Mac dùng Apple silicon, macOS 14 trở lên. |
| `WhisperTranscriberSuite-vX.Y.Z-macOS-x64.dmg` | Mac dùng chip Intel, macOS 10.15 trở lên. |

Linux chạy từ mã nguồn: [../../platform/linux/README.md](../../platform/linux/README.md).

Bản dựng FFmpeg đi kèm là một bản dùng giấy phép GPL. Mã nguồn tương ứng của nó được đính kèm trong mỗi bản phát hành
dưới dạng các tệp `WhisperTranscriberSuite-vX.Y.Z-source-ffmpeg-*`; liên kết cụ thể có tại
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

ffmpeg và yt-dlp đã được đóng gói sẵn. Ở lần chạy đầu tiên, cửa sổ bắt đầu nhanh sẽ cho phép bạn chọn
mô hình nhận dạng giọng nói cho ngôn ngữ của bạn: Nhanh (Fast - tương ứng mô hình Small, khoảng 500 MB) hoặc Chất lượng tốt nhất (Best
quality - lớn tới khoảng 3 GB); nó chỉ tải xuống một lần, ở lần sử dụng đầu tiên. Khuyến nghị cấu hình có 8 GB
RAM; trên CPU, mô hình Large tốn khoảng 1.5–2.5 lần thời lượng
của âm thanh để xử lý, và mô hình Small mất khoảng một nửa thời lượng, nếu dùng NVIDIA GPU sẽ nhanh hơn nhiều. Các bản dựng trên Windows không có chữ ký mã và bản Mac không
được chứng thực (notarized), do đó SmartScreen và Gatekeeper sẽ hiện cảnh báo trong lần khởi động đầu;
[../INSTALL.md](../INSTALL.md) sẽ hướng dẫn bạn cách vượt qua. Để cập nhật, chỉ cần chạy
trình cài đặt mới đè lên cái cũ; các thiết lập của bạn sẽ được giữ nguyên.

**Số lượt tải xuống theo phiên bản** (mỗi huy hiệu chỉ đếm lượt tải của phiên bản cụ thể đó — các phiên bản cũ vẫn được duy trì và số đếm của chúng không bao giờ bị làm mới):

[![v2.1.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.1.0/total?label=v2.1.0&color=207a80)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.1.0)
[![v2.0.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v2.0.0/total?label=v2.0.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0)
[![v1.9.3](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.3/total?label=v1.9.3&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.3)
[![v1.9.1](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.1/total?label=v1.9.1&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.1)
[![v1.9.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.9.0/total?label=v1.9.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.9.0)
[![v1.8.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.8.0/total?label=v1.8.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.8.0)
[![v1.7.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.7.0/total?label=v1.7.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.7.0)
[![v1.6.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.6.0/total?label=v1.6.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.6.0)
[![v1.5.0](https://img.shields.io/github/downloads/Milomilo777/whisper-transcriber-suite/v1.5.0/total?label=v1.5.0&color=8a8a8a)](https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v1.5.0)

## Dữ liệu gì được gửi khỏi máy tính của bạn

Với cấu hình mặc định, các tệp âm thanh và văn bản của bạn sẽ hoàn toàn nằm lại trên máy tính.
Ứng dụng có kết nối mạng để:

- tải xuống mô hình hoặc các thành phần tùy chọn trong lần đầu chúng được cần đến;
- thiết lập trực tuyến khi khởi động và tự động kiểm tra bản cập nhật mỗi ngày trên GitHub,
  việc này chỉ nhằm thông báo cho bạn khi có phiên bản mới;
- thu thập thống kê sử dụng, được bật theo mặc định, sau khi hoàn thành mỗi bản phiên âm: mô hình,
  ngôn ngữ, thời lượng, số lượng từ, phiên bản ứng dụng, hệ điều hành, cấu hình CPU và
  RAM, và khu vực, tuyệt đối không gửi tên tệp. Tắt nó trong trình đơn
  **Help → Usage statistics**.

Âm thanh và văn bản phiên âm chỉ được gửi đi khi bạn chọn công cụ đám mây (Gemini API
hoặc Google Cloud Speech-to-Text) hoặc tự kết nối với một nhà cung cấp AI từ xa.
Tính năng **File → Work offline** sẽ dừng tất cả việc kết nối mạng. Bạn có thể xem chi tiết mọi kết nối trong
[../CONFIG.md](../CONFIG.md#network-use).

## Tài liệu (Documentation)

[Cài đặt](../INSTALL.md) · [Cấu hình](../CONFIG.md) ·
[Phiên âm trực tiếp](../LIVE.md) · [Chế độ mạng nội bộ và API](../SERVER.md) ·
[Công cụ đám mây](../CLOUD_STT.md) · [Kiến trúc ứng dụng](../ARCHITECTURE.md) ·
[Nhật ký thay đổi (Changelog)](../CHANGELOG.md) · [Toàn bộ tài liệu](../README.md)

## Dựng từ mã nguồn (Build from source)

```cmd
git clone https://github.com/Milomilo777/whisper-transcriber-suite.git
cd whisper-transcriber-suite
pip install -r requirements.txt
python gui.py
```

Yêu cầu Python 3.11 trở lên. Các đường dẫn dựng ứng dụng (Build pipelines): [../BUILD.md](../BUILD.md). Kiểm thử và gửi pull request:
[../../CONTRIBUTING.md](../../CONTRIBUTING.md).

## Đóng góp và liên hệ

- **Lỗi và yêu cầu tính năng:** [GitHub Issues](https://github.com/Milomilo777/whisper-transcriber-suite/issues)
- **Câu hỏi và ý tưởng:** [GitHub Discussions](https://github.com/Milomilo777/whisper-transcriber-suite/discussions)
- **Mọi vấn đề khác:** qua email, thông qua
  [Phần liên hệ (Contact) của website](https://whisper-transcriber-suite.com/#contact)
- **Báo cáo bảo mật:** [../../SECURITY.md](../../SECURITY.md)

Dự án này tuân thủ theo [Bộ quy tắc ứng xử (Contributor Covenant)](../../.github/CODE_OF_CONDUCT.md).
Nếu ứng dụng giúp bạn tiết kiệm thời gian, một sao (Star) ở đầu trang sẽ giúp người khác
tìm thấy nó dễ dàng hơn.

## Dự án này được xây dựng như thế nào

Người bảo trì phát triển dự án với sự trợ giúp to lớn từ các trợ lý mã hóa AI (chủ yếu là Claude). Việc kiểm tra kiểu (Type checks)
và các bài kiểm tra chức năng (unit tests) phải vượt qua trước mỗi lần commit, và CI chạy lại chúng trên Windows và Linux sau
mỗi lần đẩy (push) lên mã nguồn. [Quy trình phát hành](../RELEASE_PROCESS.md) bao gồm cả bước kiểm tra cài đặt thủ công trên một
máy thực. Các commit được thực hiện với sự hỗ trợ của AI hiện sẽ được ghi tên mô hình trong dòng `Assisted-by:`; nhiều commit
cũ hơn thường mang dòng `Co-Authored-By: Claude` thay thế.

## Giấy phép (License)

Copyright (c) 2026 translation-robot (co-author). Dự án này nằm ở kho lưu trữ,
[Milomilo777/whisper-transcriber-suite](https://github.com/Milomilo777/whisper-transcriber-suite).
Mã nguồn chính của dự án được phân phối theo [Giấy phép BSD 3-Clause](../../LICENSE). Các công cụ
đóng gói đi kèm, môi trường thực thi Python và các mô hình giữ nguyên giấy phép của chính chúng; xem thêm ở
[../../THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
