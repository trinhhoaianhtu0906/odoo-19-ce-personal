# Triển khai addon kế toán Việt Nam (Odoo 19 Community)

Gói này có 4 addon:

| Addon | Chức năng | Phụ thuộc |
|---|---|---|
| `l10n_vn_financial_statements` | Báo cáo tài chính B01-DN, B02-DN, B03-DN theo Thông tư 99/2025/TT-BTC: xem trên màn hình, so sánh nhiều kỳ, xuất Excel, in PDF | `account`, `l10n_vn` (có sẵn trong Odoo) |
| `l10n_vn_consolidation` | Báo cáo hợp nhất B01-DN/HN, B02-DN/HN, bút toán loại trừ tự động | `l10n_vn_financial_statements` |
| `l10n_vn_ifrs` | Báo cáo IFRS = sổ VAS + sổ điều chỉnh IFRS (IAS 1, IAS 7), riêng và hợp nhất; tự tạo sổ "Điều chỉnh IFRS" cho từng công ty | `l10n_vn_consolidation` |
| `vietqr_tax_lookup` | Nút "Lấy thông tin MST" trên khách hàng doanh nghiệp (gọi api.vietqr.io) | `contacts` |

Không phụ thuộc bộ addon Odoo Mates (`om_*`, `accounting_pdf_reports`); chạy chung được với chúng.

## Yêu cầu

- Odoo **19.0 Community** (đã kiểm tra trên image `odoo:19.0`, bản 19.0-20261015).
- Thư viện Python: `xlsxwriter`, `requests` — đã có sẵn trong image Odoo chính thức.
- Server ra được Internet tới `https://api.vietqr.io` (chỉ cần cho `vietqr_tax_lookup`).
- Công ty dùng chart tài khoản Việt Nam của `l10n_vn` (đã theo danh mục TT99).

## Các bước (stack `Tricasia/odoo-dev`)

1. Giải nén vào thư mục addons (`my_modules/`, được mount vào `/mnt/extra-addons`):

   ```sh
   unzip vn_accounting_addons_*.zip -d /tmp/vn_accounting
   cp -r /tmp/vn_accounting/l10n_vn_financial_statements /tmp/vn_accounting/l10n_vn_consolidation \
         /tmp/vn_accounting/l10n_vn_ifrs /tmp/vn_accounting/vietqr_tax_lookup my_modules/
   ```

2. Cài đặt (từ thư mục gốc repo `odoo-dev`; thay `<db>` bằng tên database, vd. `dev-pg18.6`). Nên sao lưu database trước.

   ```sh
   docker compose run --rm odoo odoo -d <db> -i l10n_vn_ifrs,vietqr_tax_lookup --load-language=vi_VN --stop-after-init
   docker compose restart odoo
   ```

   `l10n_vn_ifrs` tự kéo theo `l10n_vn_consolidation` và `l10n_vn_financial_statements`. Không cần IFRS thì cài `l10n_vn_consolidation`; không cần hợp nhất thì cài `l10n_vn_financial_statements`.

   Nên bật cả tiếng Anh lẫn tiếng Việt trong database (Cài đặt → Ngôn ngữ) để người dùng chuyển qua lại được.

3. Nâng cấp khi có bản mới:

   ```sh
   docker compose run --rm odoo odoo -d <db> -u l10n_vn_financial_statements,l10n_vn_consolidation,l10n_vn_ifrs,vietqr_tax_lookup --stop-after-init
   docker compose restart odoo
   ```

   Khi nâng cấp, các mẫu báo cáo gốc (VAS và IFRS) bị ghi đè. Muốn tuỳ chỉnh công thức thì nhân bản mẫu rồi sửa bản sao.

## Sau khi cài

- Ngôn ngữ: addon viết bằng tiếng Anh, có bản dịch tiếng Việt (`i18n/vi.po`). Người dùng chọn **Tiếng Việt** trong Tuỳ chọn cá nhân để thấy đúng chữ của mẫu TT99 khi xem và in.
- Menu: *Kế toán → Báo cáo → Báo cáo tài chính VAS* (*Accounting → Reporting → Vietnamese Financial Statements*). Danh sách báo cáo chia 4 nhóm: VAS riêng, VAS hợp nhất, IFRS riêng, IFRS hợp nhất.
- IFRS: bút toán điều chỉnh IFRS ghi vào sổ "Điều chỉnh IFRS" (trường *Sổ* = *Chỉ điều chỉnh IFRS*). Báo cáo VAS tự bỏ sổ này, báo cáo IFRS cộng vào. Sổ nhật ký nào chỉ dùng cho VAS thì đặt *Sổ* = *Chỉ VAS*.
- Phân quyền: nhóm *Xem kế toán* (`account.group_account_readonly`) và *Quản trị hoá đơn* (`account.group_account_manager`) được xem báo cáo; sửa mẫu báo cáo và nhóm hợp nhất cần quyền quản trị.
- Báo cáo hợp nhất: tạo nhóm ở *Hợp nhất → Nhóm hợp nhất*, khai báo công ty mẹ, thành viên, tỷ lệ lợi ích, ngày mua. Kế toán phải được cấp quyền vào **mọi** công ty trong nhóm.

## Kiểm tra nhanh sau triển khai

```sh
# chạy test của 4 addon trong một database tạm, rồi xoá database đó
docker compose run --rm -T odoo odoo -d vn_fs_test_tmp -i l10n_vn_ifrs,vietqr_tax_lookup \
  --test-tags /l10n_vn_financial_statements,/l10n_vn_consolidation,/l10n_vn_ifrs,/vietqr_tax_lookup \
  --stop-after-init --log-level=test
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --force vn_fs_test_tmp'
```

Kết quả mong đợi: 54 test, không có dòng `ERROR` hay `FAIL`.

Tài liệu chi tiết (bảng, field, logic, sơ đồ): `VN_Accounting_Documentation.pdf` trong gói này.
