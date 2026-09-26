---
name: coding-simple
description: >
  Đơn giản hóa, tái cấu trúc, review và viết code để đạt độ rõ ràng cao nhất mà vẫn giữ nguyên hành vi.
  Sử dụng khi code đang chạy đúng nhưng khó đọc, khó bảo trì, khó test, khó debug hoặc khó học hơn mức cần thiết.
  Ưu tiên mạnh code rõ ràng, dễ đọc cho người mới nhưng vẫn đạt chất lượng production hơn là code khéo léo,
  quá ngắn, quá nâng cao hoặc phụ thuộc nhiều vào syntax khó. Khi đưa ra một coding pattern,
  phải giải thích đó là pattern production/industry được dùng rộng rãi, convention riêng của project,
  hay chỉ là lựa chọn custom trong implementation.
---

# Đơn giản hóa Code

> Lấy cảm hứng từ [Claude Code Simplifier plugin](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-simplifier/agents/code-simplifier.md).
> Được điều chỉnh thành một skill độc lập với model, tập trung vào **độ rõ ràng, chất lượng production, giá trị học tập và khả năng bảo trì**.

## 1. Mục tiêu

Viết và đơn giản hóa code sao cho:

1. **Dễ đọc**
2. **Dễ hiểu**
3. **Dễ debug**
4. **Dễ sửa đổi**
5. **An toàn để dùng trong production**
6. **Nhất quán với codebase hiện tại**
7. **Có giá trị học tập cho developer chưa vững coding cơ bản**
8. **Đơn giản nhất có thể, nhưng không được đơn giản hóa quá mức so với bài toán production thực tế**

Mục tiêu **không phải là ít dòng code hơn**.

Mục tiêu là:

> Một engineer mới vào team phải có thể hiểu code nhanh mà không cần mất thời gian giải mã những syntax khéo léo hoặc quá nén.

Luôn ưu tiên:

```text
code rõ ràng
    >
code ngắn
    >
code khéo léo
```

khi các mục tiêu này xung đột với nhau.

---

# 2. Hồ sơ học tập của User

Giả định user:

- vẫn chưa vững programming cơ bản;
- có thể chưa nhớ các syntax nâng cao;
- muốn học những pattern có thể áp dụng vào công việc engineering thực tế;
- thích code rõ ràng, tường minh hơn code bị nén;
- muốn code production chuyên nghiệp nhưng không phức tạp quá mức;
- muốn comment và docstring giải thích rõ những ý quan trọng;
- muốn biết một pattern là:
  - thực hành engineering chuyên nghiệp được dùng rộng rãi,
  - phổ biến trong các công ty công nghệ lớn,
  - bắt buộc hoặc được khuyến nghị bởi framework,
  - convention riêng của codebase hiện tại,
  - hay chỉ là một lựa chọn thiết kế custom.

Vì vậy, code được tạo ra phải tối ưu đồng thời cho:

```text
giá trị học tập + giá trị production
```

Không được hy sinh một bên nếu không thực sự cần thiết.

---

# 3. Quy tắc quan trọng: Không mặc định dùng syntax khéo léo hoặc bị nén

Không tối ưu code theo số ký tự ít nhất.

Tránh syntax ngắn hoặc nâng cao khi cách viết tường minh dễ hiểu hơn.

Các dạng nên tránh theo mặc định:

- ternary lồng nhau sâu;
- one-liner khéo léo;
- comprehension phức tạp;
- chuỗi transform có nhiều business logic nhét chung;
- side effect bị ẩn;
- thủ thuật ngôn ngữ khó hiểu;
- metaprogramming nếu không có lý do mạnh;
- decorator không cần thiết;
- operator overloading không cần thiết;
- generic/type-system nâng cao khi type đơn giản là đủ;
- nhiều thao tác bị nhét vào một expression;
- functional programming pipeline quá dày;
- từ viết tắt khó hiểu;
- abstraction được tạo quá sớm.

## Không nên

```python
users = [u.name for u in users if u.active and u.role in allowed if not u.deleted]
```

Đây là Python hợp lệ, nhưng người mới phải giải mã nhiều điều kiện trong cùng một dòng.

## Nên ưu tiên

```python
active_user_names = []

for user in users:
    if not user.active:
        continue

    if user.role not in allowed_roles:
        continue

    if user.deleted:
        continue

    active_user_names.append(user.name)
```

Phiên bản này dài hơn nhưng control flow nhìn thấy rõ.

Nếu dạng ngắn thực sự rõ hơn và rất phổ biến, vẫn có thể dùng, nhưng không được tự động chọn chỉ vì nó ngắn hơn.

---

# 4. Ưu tiên syntax đơn giản trước

Khi nhiều implementation đều đúng như nhau, chọn syntax dễ học và dễ bảo trì nhất.

Ưu tiên:

```python
if user is None:
    raise ValueError("User is required")
```

thay vì các construct gián tiếp không cần thiết.

Ưu tiên:

```python
user = await repository.get_user(user_id)

if user is None:
    raise UserNotFoundError(user_id)

return user
```

thay vì:

```python
return await repository.get_user(user_id) or raise_user_not_found(user_id)
```

Ưu tiên intermediate variable khi nó giúp các bước quan trọng hiện rõ.

## Nên ưu tiên

```python
password_bytes = password.encode("utf-8")
password_hash_bytes = bcrypt.hashpw(
    password_bytes,
    bcrypt.gensalt(),
)
password_hash = password_hash_bytes.decode("utf-8")

return password_hash
```

Phiên bản ngắn hơn có thể được đưa ra sau như lựa chọn bổ sung, nhưng phiên bản chính nên tối ưu cho khả năng hiểu.

---

# 5. Production Quality không có nghĩa là phải phức tạp tối đa

Không được đánh đồng "production code" với:

- quá nhiều layer;
- design pattern ở mọi nơi;
- factory ở mọi nơi;
- dependency injection ở mọi nơi;
- interface cho mọi class;
- validation quá mức;
- quá nhiều exception class;
- quá nhiều configuration;
- abstraction tối đa.

Production engineering nghĩa là chọn đủ cấu trúc để đảm bảo:

- đúng đắn;
- dễ bảo trì;
- có khả năng quan sát hệ thống khi cần;
- dễ test;
- bảo mật;
- responsibility rõ ràng;
- failure behavior có thể dự đoán.

Dùng **architecture đơn giản nhất nhưng vẫn đáp ứng yêu cầu thật**.

---

# 6. Phân loại Big-Tech / Industry Pattern

Mỗi khi đưa vào architecture, structure hoặc coding pattern quan trọng, hãy phân loại nó.

Khi phù hợp, dùng một trong các nhãn sau:

### A. `Industry-standard / widely used`

Thực hành được chấp nhận rộng rãi trong nhiều codebase chuyên nghiệp.

Ví dụ:

- dependency injection tại application boundary;
- một database transaction/session cho mỗi request hoặc unit of work;
- structured logging;
- quản lý configuration rõ ràng;
- automated test;
- code review;
- tách transport/API layer khỏi business logic.

### B. `Common big-tech-style engineering pattern`

Pattern phù hợp với kiểu engineering thường thấy trong các tổ chức lớn, trưởng thành như Google, Meta, Microsoft, Amazon, Netflix, v.v.

Quan trọng:

Không được tuyên bố:

> "Google dùng chính xác đoạn code này."

nếu không có bằng chứng đã được kiểm chứng.

Thay vào đó nên nói:

> "Cách này phù hợp với các thực hành engineering production quy mô lớn thường gặp."

Các công ty lớn không dùng một architecture duy nhất.

Implementation cụ thể thay đổi theo:

- ngôn ngữ;
- team;
- sản phẩm;
- traffic;
- infrastructure;
- legacy constraint;
- internal framework.

### C. `Framework convention`

Pattern được framework/library khuyến nghị hoặc yêu cầu.

Ví dụ:

```text
FastAPI dependency injection
Django ORM conventions
React hook rules
SQLAlchemy session lifecycle
```

### D. `Project convention`

Pattern tồn tại vì repository hiện tại đã đi theo cách đó.

Nên tuân theo trừ khi có lý do mạnh để thay đổi.

### E. `Custom design choice`

Một quyết định hợp lệ được tạo riêng cho project/user hiện tại.

Không được trình bày custom choice như một best practice áp dụng cho mọi nơi.

---

# 7. Giải thích rõ trạng thái của Pattern

Với những quyết định architecture quan trọng, cung cấp giải thích ngắn như:

```text
Pattern status:
- Type: Industry-standard / framework convention
- Why used: giới hạn lifetime của database transaction
- Big-tech relevance: khái niệm này phổ biến trong backend system trưởng thành
- Project-specific part: tên helper/function cụ thể là custom
```

Không cần thêm annotation này sau mọi dòng code nhỏ.

Chỉ dùng cho các quyết định như:

- repository pattern;
- service layer;
- dependency injection;
- database session lifecycle;
- factory;
- singleton;
- tách DTO/schema;
- event-driven architecture;
- cache;
- retry;
- background worker;
- middleware;
- exception hierarchy;
- configuration architecture;
- monorepo/module boundary.

---

# 8. Giữ nguyên hành vi khi đơn giản hóa

Khi refactor code hiện có, không thay đổi code làm gì trừ khi user yêu cầu rõ.

Phải giữ nguyên:

- input;
- output;
- side effect;
- error behavior;
- thứ tự thực thi;
- database behavior;
- API behavior;
- async behavior;
- edge case.

Trước mỗi refactor, hãy tự kiểm tra:

```text
Kết quả có giống nhau không?
Error có giống nhau không?
Side effect có được giữ nguyên không?
Thứ tự thực thi có giống không?
Test hiện có vẫn pass không?
```

Nếu không chắc, không được âm thầm thay đổi behavior.

---

# 9. Hiểu trước khi sửa

Áp dụng nguyên tắc **Chesterton's Fence**:

> Không xóa hoặc viết lại một thứ cho đến khi hiểu vì sao nó tồn tại.

Trước khi đơn giản hóa code quan trọng, xác định:

- Code này chịu trách nhiệm gì?
- Ai gọi nó?
- Nó gọi những gì?
- Nó đọc hoặc sửa state nào?
- Có thể phát sinh lỗi gì?
- Test nào mô tả behavior mong đợi?
- Complexity có đến từ performance, concurrency, security, framework rule hay legacy constraint không?
- Pattern này có bị ràng buộc bởi code xung quanh không?

Nếu có repository history, dùng git history/blame khi lý do chưa rõ.

---

# 10. Tuân theo convention của project hiện tại

Trước khi đưa style mới vào, kiểm tra:

```text
CLAUDE.md
AGENTS.md
README
CONTRIBUTING
pyproject.toml
eslint/prettier config
neighboring modules
existing tests
existing architecture
```

Khớp với convention của repository về:

- naming;
- tổ chức file;
- import;
- typing;
- error handling;
- logging;
- dependency injection;
- async/sync style;
- test;
- configuration.

Một refactor đẹp về lý thuyết nhưng khiến một file lệch khỏi toàn codebase thường là refactor tệ.

---

# 11. Ưu tiên Control Flow tường minh

Ưu tiên **guard clause** và branch đơn giản.

## Khó đọc hơn

```python
def process(data):
    if data is not None:
        if data.is_valid():
            if data.has_permission():
                return do_work(data)
            else:
                raise PermissionError("No permission")
        else:
            raise ValueError("Invalid data")
    else:
        raise TypeError("Data is None")
```

## Nên ưu tiên

```python
def process(data):
    if data is None:
        raise TypeError("Data is None")

    if not data.is_valid():
        raise ValueError("Invalid data")

    if not data.has_permission():
        raise PermissionError("No permission")

    return do_work(data)
```

Lý do:

- từng điều kiện lỗi nhìn thấy rõ;
- giảm nesting;
- happy path dễ tìm;
- debug dễ hơn.

Đây là **professional pattern được dùng rộng rãi**, không phải trick custom của user.

---

# 12. Ưu tiên tên có ý nghĩa

Tránh tên mơ hồ:

```text
data
result
temp
val
obj
x
y
stuff
thing
cfg
usr
mgr
svc
```

trừ khi ý nghĩa của chúng thực sự quá rõ trong một scope rất nhỏ.

Ưu tiên:

```text
user
user_profile
validated_payload
password_hash
database_session
access_token
order_total
validation_errors
```

Các abbreviation phổ biến toàn ngành vẫn ổn:

```text
id
url
api
http
db
sql
jwt
```

nhưng không viết tắt biến chỉ để gõ ít ký tự hơn.

---

# 13. Một Function = Một Responsibility rõ ràng

Một function thường nên trả lời một câu hỏi hoặc thực hiện một công việc thống nhất.

Tránh function vừa:

1. validate input;
2. fetch data;
3. modify state;
4. send email;
5. write log;
6. return HTTP response;

tất cả trong một block lớn.

Nhưng cũng không chia một function đơn giản 15 dòng thành sáu function siêu nhỏ chỉ để tuân thủ rule.

Chỉ split khi nó cải thiện:

- khả năng hiểu;
- test;
- reuse;
- cô lập error;
- naming của concept quan trọng.

Không split chỉ để giảm line count.

---

# 14. Tránh rule kích thước cứng nhắc

Những số như:

```text
function > 50 lines
nesting > 3 levels
duplicate block > 5 lines
refactor > 500 lines
```

là **tín hiệu**, không phải luật.

Không refactor chỉ vì vượt threshold.

Hãy hỏi:

```text
Khả năng hiểu có thực sự giảm không?
Có nhiều responsibility bị trộn không?
Duplication có nguy cơ lệch nhau về sau không?
Việc extract có làm intent rõ hơn không?
```

Dùng engineering judgment.

---

# 15. Comment và Docstring

Comment/docstring phải **đủ chi tiết để giúp học**, nhưng không gây nhiễu.

Nên giải thích:

- responsibility;
- input;
- output;
- side effect quan trọng;
- failure case;
- quyết định không rõ ràng;
- lý do một production constraint tồn tại.

Không spam comment chỉ để dịch code sang tiếng Anh.

## Không nên

```python
# Add 1 to count
count += 1
```

## Hữu ích

```python
# Giữ retry count trong phạm vi request hiện tại.
# Nếu dùng global counter, retry state của nhiều request chạy đồng thời
# có thể bị trộn với nhau.
retry_count += 1
```

---

# 16. Style Docstring cho Code dùng để học

Với function quan trọng, ưu tiên docstring rõ ràng.

Ví dụ:

```python
def verify_password(password: str, password_hash: str) -> bool:
    """
    Kiểm tra plain-text password có khớp với bcrypt hash đã lưu hay không.

    Args:
        password:
            Password nhận từ login request.

        password_hash:
            Bcrypt hash đã được lưu trong database trước đó.

    Returns:
        True nếu password khớp hash.
        False nếu không khớp.

    Notes:
        bcrypt.checkpw() làm việc với bytes, vì vậy cả hai string
        phải được encode sang UTF-8 trước khi so sánh.

        Stored hash sai format có thể làm phát sinh ValueError.
        Ta trả về False vì một hash không hợp lệ tuyệt đối không được
        phép xác thực user thành công.
    """
```

Dùng ngôn ngữ dễ hiểu thay vì spam jargon.

Nếu thuật ngữ kỹ thuật là cần thiết, giải thích ngắn ngay lần đầu xuất hiện.

---

# 17. Không Over-Comment Production Code

Production-quality code vẫn phải dễ đọc ngay cả khi không có comment.

Ưu tiên:

```python
is_password_valid = verify_password(password, user.password_hash)

if not is_password_valid:
    raise InvalidCredentialsError()
```

thay vì:

```python
# Call password function
x = verify_password(password, user.password_hash)

# If x is false
if not x:
    # Throw error
    raise InvalidCredentialsError()
```

Comment phải thêm thông tin mà code khó tự biểu đạt.

---

# 18. Teaching Mode cho Code quan trọng

Khi trình bày code mới cho user, giải thích theo thứ tự này khi phù hợp:

```text
1. Code này giải quyết vấn đề gì
2. Nó nằm ở đâu trong system
3. Workflow thực thi
4. Code
5. Các dòng quan trọng
6. Vì sao cấu trúc này được dùng
7. Phân loại pattern
8. Alternative đơn giản hơn nếu có
9. Khi nào pattern này trở thành over-engineering
```

Không giải thích từng ký tự nếu user không yêu cầu line-by-line.

Tập trung vào concept giúp nâng kỹ năng coding có thể tái sử dụng.

---

# 19. Cho thấy Workflow trước khi nói Architecture phức tạp

Với backend code không quá đơn giản, giải thích execution flow như:

```text
HTTP request
    ↓
route/controller
    ↓
service/use-case
    ↓
repository
    ↓
database session
    ↓
database
    ↓
result đi ngược lên trên
```

Sau đó giải thích layer nào sở hữu responsibility nào.

Điều này giúp user hiểu **vì sao file/class tồn tại**, thay vì học thuộc cấu trúc folder một cách mù quáng.

---

# 20. Tránh học thuộc Pattern một cách máy móc

User muốn rule engineering có thể dùng lâu dài, nhưng pattern không được biến thành giáo điều.

Với mỗi rule quan trọng, phân biệt:

```text
Rule:
Dùng một database unit-of-work/session cho mỗi request.

Reason:
Nó giới hạn transaction lifetime và ngăn những request không liên quan
chia sẻ mutable transactional state.

Không phải rule:
"Luôn tạo session factory vì big tech làm thế."

Implementation:
Phụ thuộc framework và infrastructure.
```

Dạy theo:

```text
principle → reason → implementation
```

không phải:

```text
học thuộc syntax → copy mãi mãi
```

---

# 21. Ưu tiên Production Code "Boring"

Code "boring" thường là production code tốt.

Ưu tiên code:

- engineer khác nhìn là nhận ra ngay;
- control flow dễ đoán;
- dùng API phổ biến của library;
- dễ search;
- dễ test;
- không đòi hỏi hiểu trick.

Tránh viết code mà lợi thế chính chỉ là nhìn "cao cấp".

---

# 22. Không dùng Abstraction trước khi nó thực sự đáng giá

Tránh:

- factory-for-a-factory;
- interface chỉ có một implementation và không có nhu cầu test/mock;
- strategy pattern chỉ có một strategy;
- generic repository với hàng loạt type parameter;
- base class chỉ có một subclass;
- configuration system cho một constant;
- plugin architecture trước khi thực sự có plugin.

Chỉ đưa abstraction vào khi nó giảm duplication thật hoặc cô lập một điểm variation thật.

---

# 23. Ngoại lệ quan trọng: Requirement Production thật luôn được ưu tiên

Không cố tình làm yếu requirement production chỉ để code dễ học hơn.

Không bao giờ được đơn giản hóa mất:

- authentication;
- authorization;
- transaction boundary;
- input validation khi cần;
- security control;
- protection chống race condition;
- concurrency requirement;
- resource cleanup;
- timeout handling;
- retry bắt buộc;
- observability cần cho operation;
- data integrity constraint.

Thay vào đó:

1. giữ mechanism cần thiết;
2. implement nó rõ ràng;
3. giải thích nó đơn giản.

---

# 24. Giới hạn phạm vi thay đổi

Chỉ sửa những gì cần cho task của user.

Không cleanup ngoài phạm vi.

Khi edit code hiện có:

- giữ formatting không liên quan;
- giữ tên không liên quan;
- không reorganize cả folder nếu không có lý do;
- không refactor neighboring module chỉ vì nó chưa đẹp;
- nếu thấy dead code ngoài scope, hãy đề cập thay vì tự xóa.

Mỗi dòng bị thay đổi phải truy ngược được về:

```text
thay đổi user yêu cầu
hoặc
thứ trở nên thừa vì thay đổi đó
```

---

# 25. Refactor theo từng bước nhỏ

Với mỗi simplification quan trọng:

```text
1. Hiểu behavior hiện tại
2. Thực hiện một logical change
3. Chạy test liên quan
4. Chạy lint/type check nếu có
5. So sánh behavior
6. Tiếp tục
```

Tránh trộn:

```text
feature + refactor lớn + dependency upgrade
```

trong cùng một thay đổi, trừ khi chúng không thể tách rời.

Diff nhỏ dễ:

- review;
- debug;
- revert;
- hiểu trong git history.

Đây là professional engineering practice phổ biến.

---

# 26. Yêu cầu về Testing

Refactor thường phải giữ nguyên test hiện có.

Nếu behavior chưa rõ, thêm characterization test trước khi refactor.

Ví dụ:

```text
Bug hiện tại?
→ Viết test tái hiện bug.
→ Sửa code.
→ Test pass.

Refactor?
→ Test pass trước.
→ Refactor.
→ Cùng test đó vẫn pass sau.
```

Pure refactor giữ nguyên behavior không nên yêu cầu thay expected output.

Nếu test phải đổi, kiểm tra xem behavior có vô tình bị đổi không.

---

# 27. Error Handling

Dùng error handling rõ ràng, dễ hiểu.

Tránh:

```python
try:
    ...
except Exception:
    return None
```

trừ khi thật sự muốn ẩn mọi loại error.

Ưu tiên handle error ở layer hiểu được error đó.

Ví dụ:

```python
try:
    user = await repository.get_user(user_id)
except DatabaseError as error:
    logger.exception(
        "Failed to load user",
        extra={"user_id": user_id},
    )
    raise UserLookupError(user_id) from error
```

Không thêm `try/except` khắp nơi.

Quá nhiều error handling có thể làm code khó hiểu hơn và che mất bug.

---

# 28. Async Code

Không dùng async chỉ vì nó trông hiện đại.

Dùng async khi application/framework hưởng lợi từ non-blocking I/O như:

- database call;
- HTTP call;
- file/network I/O;
- message broker.

Tránh wrapper không cần thiết như:

```python
async def get_user(user_id: int):
    return await user_service.get_user(user_id)
```

khi wrapper không thêm responsibility hay abstraction boundary ổn định.

Tuy nhiên vẫn giữ wrapper nếu nó đại diện cho boundary có ý nghĩa như:

- authorization;
- tracing;
- caching;
- transaction management;
- domain semantics.

---

# 29. Hướng dẫn cho Python

Ưu tiên Python dễ đọc hơn Python nâng cao.

## Thường nên ưu tiên khi dạy

```python
active_users = []

for user in users:
    if user.is_active:
        active_users.append(user)
```

thay vì ngay lập tức dùng:

```python
active_users = [user for user in users if user.is_active]
```

List comprehension không phải code xấu.

Đó là Python chuẩn và phổ biến.

Nhưng nếu user vẫn đang học control flow, loop tường minh giúp hiểu execution model rõ hơn.

Sau đó có thể nói thêm:

```text
List comprehension là cách Python ngắn hơn và rất phổ biến.
Dùng nó khi điều kiện vẫn đơn giản.
```

Điều này giúp phân biệt:

```text
syntax dễ học
vs
idiomatic production syntax
```

thay vì giả vờ rằng một cách luôn luôn đúng.

---

# 30. Hướng dẫn cho TypeScript / JavaScript

Tránh nested ternary.

## Tránh

```typescript
const label = isNew
  ? "New"
  : isUpdated
    ? "Updated"
    : isArchived
      ? "Archived"
      : "Active";
```

## Ưu tiên

```typescript
function getStatusLabel(item: Item): string {
  if (item.isNew) {
    return "New";
  }

  if (item.isUpdated) {
    return "Updated";
  }

  if (item.isArchived) {
    return "Archived";
  }

  return "Active";
}
```

Không nén code chỉ vì JavaScript cho phép.

---

# 31. Hướng dẫn cho React

Ưu tiên rendering logic dễ đọc.

Ternary nhỏ vẫn chấp nhận được:

```tsx
const label = user.isAdmin ? "Admin" : "User";
```

Không tự động thay mọi `if` bằng ternary.

Với nhiều branch, ưu tiên named variable, helper function hoặc branch tường minh.

Không đưa global state, context, memoization hoặc custom hook vào nếu chúng không giải quyết vấn đề thật.

---

# 32. Hướng dẫn Database / Backend

Khi có database code, giải thích rõ ownership và lifecycle.

Ví dụ:

```text
engine
    = quản lý database connection

session factory
    = tạo Session object

session
    = một đơn vị database work / transaction context

repository
    = thực hiện database operation bằng session đó
```

Không giải thích architecture bằng khẩu hiệu kiểu:

> "vì mỗi request cần một session"

mà không giải thích:

- tại sao sharing một global mutable session nguy hiểm;
- transaction isolation;
- concurrent request;
- lifecycle;
- cleanup.

Phải dạy lý do nền tảng.

---

# 33. Hướng dẫn Dependency Injection

Không đưa dependency injection vào chỉ vì nó được xem là "enterprise".

Dùng khi nó giúp:

- quản lý resource lifecycle;
- thay implementation;
- test;
- configuration;
- tách responsibility.

Phân loại pattern:

```text
Concept:
Architecture pattern chuyên nghiệp được dùng rộng rãi.

Exact implementation:
Phụ thuộc framework/project.

Không universal:
Các công ty lớn dùng nhiều cơ chế DI khác nhau.
```

---

# 34. Hướng dẫn Repository Pattern

Không tự động thêm repository layer.

Dùng khi nó tạo boundary có ý nghĩa quanh persistence.

Hữu ích khi:

- business logic không nên phụ thuộc trực tiếp ORM detail;
- data access được reuse;
- persistence logic bắt đầu phức tạp;
- testing được lợi khi có thể thay persistence boundary.

Có thể trở thành over-engineering khi:

- project rất nhỏ;
- repository method chỉ đổi tên ORM call;
- không có business layer;
- abstraction tạo thêm file nhưng không tăng clarity.

Luôn giải thích tình huống hiện tại thuộc loại nào.

---

# 35. Hướng dẫn Service Layer

Service/use-case layer hữu ích khi business logic cần một nơi riêng biệt khỏi:

```text
HTTP framework
database implementation
UI
```

Tránh service class mà method chỉ gọi repository một-một mà không thêm domain meaning.

Ví dụ abstraction yếu:

```python
class UserService:
    async def get_user(self, user_id: int):
        return await self.repository.get_user(user_id)
```

Chỉ giữ nếu layer đó đại diện cho architecture boundary có chủ đích hoặc future responsibility đã được justify bởi project hiện tại.

---

# 36. Tín hiệu cho thấy Code có thể đơn giản hóa

Tìm các dấu hiệu:

| Tín hiệu | Cải thiện có thể dùng |
|---|---|
| Nesting sâu | Guard clause |
| Function dài có nhiều responsibility | Split theo responsibility |
| Nested ternary | if/elif/else tường minh |
| Tên khó hiểu | Đổi sang tên mô tả rõ |
| Logic lặp | Extract shared function |
| Wrapper không có responsibility | Xóa wrapper |
| Dead code | Chỉ xóa khi đã xác nhận và nằm trong scope |
| Premature abstraction | Thay bằng direct implementation |
| Expression chain quá lớn | Tạo intermediate variable |
| Side effect bị ẩn | Làm mutation hiện rõ |
| Quá nhiều boolean flag | Dùng explicit option hoặc separate operation |

Đây là heuristic, không phải lệnh rewrite tự động.

---

# 37. Bài test chất lượng Before / After

Trước khi chấp nhận simplification, so sánh:

```text
Người mới có trace execution dễ hơn không?
Engineer có kinh nghiệm có scan code nhanh không?
Responsibility có rõ hơn không?
Behavior có giữ nguyên không?
Testing có dễ hơn hoặc ít nhất không tệ đi không?
Cognitive load có giảm không?
Có tránh được abstraction không cần thiết không?
Có vẫn tuân theo project convention không?
```

Nếu không, hãy xem lại refactor.

---

# 38. Những lý do biện hộ tệ thường gặp

| Lý do | Góc nhìn engineering tốt hơn |
|---|---|
| "Một dòng sạch hơn." | Một dòng chỉ sạch hơn nếu nó dễ hiểu hơn. |
| "Senior developer viết code ngắn." | Senior developer tối ưu maintainability, không tối ưu số ký tự. |
| "Design pattern này chuyên nghiệp hơn." | Pattern chỉ hữu ích khi giải quyết vấn đề thật. |
| "Big tech làm thế." | Phải xác minh principle; implementation khác nhau theo công ty/team. |
| "Sau này có thể cần." | Đừng trả complexity cost trước khi có requirement thật. |
| "Framework support." | Framework support không có nghĩa project cần nó. |
| "Types giải thích hết rồi." | Type mô tả cấu trúc; naming và design giải thích intent. |
| "Nhiều comment sẽ dễ học hơn." | Code rõ trước; comment giải thích intent không rõ. |
| "Nhiều layer = architecture tốt hơn." | Mỗi layer phải có responsibility thực sự. |

---

# 39. Red Flags

Dừng và xem lại khi:

- code ngắn hơn nhưng khó đọc hơn;
- refactor vô tình đổi behavior;
- phải làm yếu test để pass;
- syntax nâng cao được đưa vào mà không có lợi ích thật;
- số abstraction nhiều hơn use case;
- phải viết comment để giải thích code khó hiểu mà đáng ra có thể rewrite;
- một pattern bị gọi là "best practice" nhưng không có context;
- custom choice được trình bày như universal rule;
- tuyên bố "Google/Meta/Amazon style" mà không có evidence;
- code được tối ưu cho elegance thay vì maintainability;
- sửa file không liên quan;
- security/error handling bị bỏ chỉ để code sạch hơn.

---

# 40. Response Style bắt buộc khi viết Code

Khi viết code cho user này:

### Mặc định

- dùng syntax đầy đủ, dễ đọc;
- dùng tên biến mô tả rõ;
- tránh clever one-liner;
- tránh advanced syntax nếu không thật sự cần;
- giữ control flow tường minh;
- thêm type hint hữu ích;
- thêm comment/docstring hữu ích;
- giải thích thuật ngữ kỹ thuật lạ;
- giữ architecture phù hợp production;
- tránh abstraction không cần thiết.

### Nếu advanced syntax thực sự có lợi

Làm theo thứ tự:

```text
1. Đưa phiên bản dễ đọc trước.
2. Giải thích advanced syntax.
3. Có thể đưa phiên bản idiomatic ngắn hơn sau.
4. Giải thích khi nào team production có kinh nghiệm sẽ chọn mỗi cách.
```

Không bắt user học phiên bản bị nén trước khi hiểu execution thực tế.

---

# 41. Giải thích Pattern bắt buộc

Với mỗi **architecture decision quan trọng và không tầm thường**, giải thích:

```text
Pattern:
Đang dùng gì?

Reason:
Nó giải quyết vấn đề gì?

Classification:
- Industry-standard?
- Common big-tech-style engineering principle?
- Framework convention?
- Project convention?
- Custom choice?

Trade-off:
Nó đưa thêm complexity gì?

When NOT to use:
Khi nào nó trở thành không cần thiết hoặc over-engineered?
```

Giữ phần giải thích ngắn gọn trừ khi user yêu cầu deep dive.

---

# 42. Production Checklist

Trước khi hoàn tất code/refactor task, kiểm tra:

- [ ] Behavior được giữ nguyên trừ khi user yêu cầu đổi.
- [ ] Code dễ hiểu hơn trước.
- [ ] Không thêm clever short syntax không cần thiết.
- [ ] Tên variable/function quan trọng có ý nghĩa.
- [ ] Function có responsibility thống nhất.
- [ ] Comment giải thích intent, không giải thích syntax hiển nhiên.
- [ ] Function quan trọng có docstring hữu ích khi phù hợp.
- [ ] Error handling không bị làm yếu.
- [ ] Security behavior không bị làm yếu.
- [ ] Resource lifecycle đúng.
- [ ] Async chỉ dùng khi có lý do.
- [ ] Test pass.
- [ ] Lint/format/type check pass nếu có.
- [ ] Không trộn refactor ngoài scope.
- [ ] Tuân thủ project convention.
- [ ] Pattern quan trọng được phân loại đúng.
- [ ] Custom choice không bị gắn nhãn sai thành universal best practice.
- [ ] Code vẫn đủ đơn giản cho developer chưa vững basic có thể học.
- [ ] Code vẫn phù hợp professional production use.

---

# 43. Nguyên tắc cuối cùng

Mục tiêu không phải:

```text
beginner toy code
```

và cũng không phải:

```text
clever senior-looking code
```

Mục tiêu là:

```text
đơn giản
tường minh
đúng
chuyên nghiệp
production-ready
dễ debug
dễ review
dễ học
```

Một senior engineer phải có thể tôn trọng thiết kế.

Một beginner phải có thể lần theo execution.

Khi có thể đạt cả hai, hãy chọn cả hai.
