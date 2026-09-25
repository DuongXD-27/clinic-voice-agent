import { ArrowLeft } from "lucide-react";
import { Link } from "react-router";

import { PageHeader } from "../components/layout/PageHeader";
import styles from "./NotFoundPage.module.css";

export function NotFoundPage() {
  return (
    <>
      <PageHeader
        eyebrow="404"
        title="Không tìm thấy trang"
        description="Đường dẫn này không tồn tại hoặc trang chưa được chuyển sang giao diện mới."
      />
      <Link to="/" className={styles.back}>
        <ArrowLeft aria-hidden />
        Về trang tổng quan
      </Link>
    </>
  );
}
