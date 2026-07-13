# Novel → Ava Audio + SRT + MP4

Công cụ nhận một file TXT hoặc một URL chương truyện mà bạn có quyền sử dụng, tạo:

- `narration_ava.mp3`: giọng `en-US-AvaMultilingualNeural`;
- `subtitles.en.srt`: thời gian lấy trực tiếp từ WordBoundary của TTS, độ phân giải mili giây;
- `word_timings.json`: mốc đầu/cuối từng từ để có thể kiểm tra hoặc dựng lại cue;
- `raw_word_timings.json`: WordBoundary gốc của Ava, được lưu trước alignment để phục hồi nếu source có token đặc biệt;
- `video.mp4`: video 1080p dùng ảnh nền, kèm audio và subtitle tiếng Anh dạng soft-sub;
- `source.txt` và `metadata.json` để kiểm tra nguồn vào/cấu hình.

## Thư mục project

Project hiện nằm trong hai thư mục cùng tên. File chạy chính có đường dẫn Windows:

```text
C:\Users\ACER\Desktop\autovideo_tool\autovideo_tool\novel_video.py
```

Vì vậy, trước khi chạy bất kỳ lệnh nào, cần đi vào **thư mục con có file `novel_video.py`**.

### Git Bash

```bash
cd /c/Users/ACER/Desktop/autovideo_tool/autovideo_tool
pwd
ls novel_video.py requirements.txt
```

Kết quả `pwd` đúng phải là:

```text
/c/Users/ACER/Desktop/autovideo_tool/autovideo_tool
```

Nếu `ls novel_video.py` báo không tìm thấy file thì chưa đứng đúng thư mục và không nên chạy tiếp.

## Cài đặt

Yêu cầu Python 3.10+ và FFmpeg có trong `PATH`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Cài đặt bằng Git Bash

Chạy sau khi đã `cd` đúng thư mục:

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Khi kích hoạt thành công, đầu dòng Git Bash sẽ có `(.venv)`.

## Chạy từ TXT

### Git Bash — ví dụ Chapters 26–32

Đầu tiên kiểm tra file đầu vào:

```bash
pwd
ls novel_video.py
ls text_novel/Chapter_26_32.txt
ls image/image_1.png
```

Sau đó chạy:

```bash
python novel_video.py \
  --text-file "text_novel/Chapter_26_32.txt" \
  --title "I Build a Shelter in the Eternal Night - Chapters 26-32" \
  --background "image/image_1.png" \
  --output-dir "output/chapters_26_32" \
  --rate=-7% \
  --pitch=-2Hz \
  --cue-max-chars 104 \
  --cue-max-seconds 7 \
  --subtitle-line-chars 52
```

Không nhập ký tự `$` ở đầu lệnh; `$` chỉ là ký hiệu prompt thường thấy trong tài liệu.

Kết quả được ghi vào:

```text
output/chapters_26_32/
```

### Chạy từ thư mục ngoài mà không cần `cd`

Nếu đang đứng tại `/c/Users/ACER/Desktop/autovideo_tool`, phải ghi thêm tên thư mục con vào mọi đường dẫn:

```bash
python autovideo_tool/novel_video.py \
  --text-file "autovideo_tool/text_novel/Chapter_26_32.txt" \
  --title "I Build a Shelter in the Eternal Night - Chapters 26-32" \
  --background "autovideo_tool/image/image_1.png" \
  --output-dir "autovideo_tool/output/chapters_26_32" \
  --rate=-7% \
  --pitch=-2Hz \
  --cue-max-chars 104 \
  --cue-max-seconds 7 \
  --subtitle-line-chars 52
```

Khuyến nghị dùng cách đầu tiên: `cd` vào đúng thư mục con rồi chạy đường dẫn ngắn.

### PowerShell

```powershell
python novel_video.py `
  --text-file "C:\duong-dan\chapter-1.txt" `
  --title "Tên truyện - Chapter 1" `
  --background "C:\duong-dan\background.jpg" `
  --output-dir "output\chapter-1"
```

### Lỗi `can't open file ...novel_video.py`

Thông báo này có nghĩa Python không tìm thấy file chương trình trong thư mục hiện tại. Kiểm tra bằng:

```bash
pwd
ls
find . -maxdepth 2 -name novel_video.py
```

Trong project này, sửa nhanh bằng:

```bash
cd /c/Users/ACER/Desktop/autovideo_tool/autovideo_tool
source .venv/Scripts/activate
python novel_video.py --help
```

Nếu lệnh cuối hiện phần hướng dẫn tham số thì vị trí và môi trường Python đã đúng.

## Chạy từ URL

Chỉ dùng với nội dung bạn có quyền truy cập và chuyển đổi. Một số trang (trong đó có thể có WebNovel) chặn trình tải tự động; khi đó hãy lưu nội dung thành TXT.

```powershell
python novel_video.py `
  --url "https://example.com/chapter-1" `
  --confirm-rights `
  --background "C:\duong-dan\background.jpg" `
  --output-dir "output\chapter-1"
```

Thử nhanh một phần đầu với `--sample-chars 500`. Có thể chỉnh biểu cảm nhịp đọc bằng `--rate -8%` và `--pitch -3Hz`. Edge TTS không hỗ trợ điều khiển cảm xúc bằng style tag; dấu câu trong TXT có ảnh hưởng lớn nhất đến cách Ava ngắt nghỉ.

## Caption theo câu và ý hoàn chỉnh

Tool ưu tiên kết thúc cue ở cuối câu hoặc cuối dòng/đoạn trong TXT. Nếu một câu quá dài, tool chỉ tách ở ranh giới có ý nghĩa như dấu phẩy, chấm phẩy, dấu hai chấm hoặc liên từ. Caption dài được tự xuống dòng nhưng timestamp vẫn lấy từ từ đầu tiên đến từ cuối cùng của cue.

`--cue-max-chars` là giới hạn đọc dễ ưu tiên, không phải giới hạn phá câu. Nếu không tìm được ranh giới ý hợp lệ tại giới hạn này, tool sẽ gộp đến dấu kết ý kế tiếp; cue ngoại lệ có thể dài hơn và xuống thêm dòng để không tạo caption cụt nghĩa.

Mặc định, cue hiện tại được giữ trên màn hình đến đúng thời điểm cue kế tiếp bắt đầu. Khoảng nghỉ trong lời đọc vì thế không tạo frame subtitle trống hoặc hiệu ứng caption nhấp nháy khi chuyển cue.

Edge đôi khi tách nhiều hơn hoặc ít hơn source một token đối với ký hiệu, số hoặc từ ghép. Tool dùng sequence alignment để tự bỏ token timing thừa, nội suy token thiếu và chỉ dừng khi tỷ lệ khớp dưới 98%. Raw timing luôn được ghi trước bước này nên lỗi alignment không làm mất dữ liệu TTS.

Nếu log có dòng `Alignment adjusted`, đó không phải lỗi. Nó cho biết Edge đã tách token khác source và tool đã tự căn lại. Sau khi chạy xong, dùng `verify_output.py` để xác nhận `match_ratio: 1.0`.

Chạy regression test sau khi sửa code:

```bash
python -m unittest -v test_novel_video.py
```

Test bao gồm token Edge thừa, token Edge thiếu và việc giữ cue cũ đến lúc cue mới xuất hiện.

Trước khi tạo giọng, tool tự loại page-marker `1`/`2` bị dính sau dấu kết câu hoặc cuối tiêu đề chương (nhưng vẫn giữ số như `Level 2`). Các dòng separator chỉ chứa `-`, `...` hoặc `…` được dùng như khoảng nghỉ và không tạo caption vô nghĩa.

Các giá trị mặc định phù hợp video 16:9:

```powershell
python novel_video.py `
  --text-file "chapter.txt" `
  --background "background.png" `
  --output-dir "output\chapter" `
  --cue-max-chars 104 `
  --cue-max-seconds 7 `
  --subtitle-line-chars 52
```

- `--cue-max-chars`: giới hạn tổng ký tự của một cue; tăng lên nếu muốn giữ nhiều câu dài nguyên vẹn hơn.
- `--cue-max-seconds`: thời gian nói tối đa của cue.
- `--subtitle-line-chars`: số ký tự gần đúng trước khi tự xuống dòng; không làm thay đổi timestamp.

Để lời đọc và caption có ý rõ ràng, nên để mỗi câu/đoạn hội thoại trên một dòng riêng trong TXT và giữ đầy đủ dấu `.`, `?`, `!`, `,`, `;`, `:`.

### Chỉnh lại caption mà không tạo lại audio

Sau một lần chạy thành công, `word_timings.json` lưu timing từng từ của Ava. Có thể đổi giới hạn cue, cách xuống dòng và dựng lại SRT/MP4 mà không gọi TTS:

```powershell
python recaption.py `
  --output-dir "output\chapter" `
  --background "background.png" `
  --cue-max-chars 104 `
  --cue-max-seconds 7 `
  --subtitle-line-chars 52
```

Thêm `--skip-video` nếu chỉ muốn thử lại file SRT. Khi đã hài lòng, chạy lại không có `--skip-video` để thay `video.mp4`. Lệnh này lấy lại toàn bộ viết hoa, dấu câu, dấu ngoặc và ranh giới dòng trực tiếp từ `source.txt`, còn thời gian lấy từ `word_timings.json`.

MP4 chứa subtitle tiếng Anh dạng soft-sub. Trình phát như VLC có thể bật/tắt subtitle; file SRT rời luôn được giữ cạnh video.
